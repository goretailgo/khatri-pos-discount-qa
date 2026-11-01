# -*- coding: utf-8 -*-
"""Server-side PDF receipt for khatri_pos_discount.

Mirrors the POS receipt logic in static/src/js/order_line.js so the PDF
matches the printed receipt (Section A / Section B split, MRP strikethrough,
Total Saved / YOU PAY). Read-only: does not change POS behaviour.

JSON-RPC (execute_kw on pos.order):
    get_receipt_pdf          args=[[order_id]]
    get_receipt_pdf_by_ref   args=["2614-9-000036"]
Returns {order_id, receipt_no, filename, pdf_base64}
"""
import base64
import html
import json
import logging
import re
from urllib.parse import quote

from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

REPORT_REF = 'khatri_pos_discount.action_report_khatri_receipt_pdf'
GRG_LOGO_PATH = 'khatri_pos_discount/static/src/img/goretailgo_logo.png'
GRG_CONTACT = '+919981161544'


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_receipt_pdf(self):
        self.ensure_one()
        tz = self.env.user.tz or 'Asia/Kolkata'
        order = self.with_context(tz=tz)
        pdf, _ = self.env['ir.actions.report'].with_context(tz=tz)._render_qweb_pdf(REPORT_REF, order.ids)
        ref = self.pos_reference or self.name or str(self.id)
        return {
            'order_id': self.id,
            'receipt_no': ref,
            'filename': '%s.pdf' % re.sub(r'[^\w.-]+', '_', ref),
            'pdf_base64': base64.b64encode(pdf).decode(),
        }

    @api.model
    def get_receipt_pdf_by_ref(self, pos_reference):
        pos_reference = (pos_reference or '').strip()
        order = self.search(['|', ('pos_reference', '=', pos_reference), ('name', '=', pos_reference)],
                            limit=1, order='id desc')
        if not order:
            order = self.search([('pos_reference', 'ilike', pos_reference)], limit=1, order='id desc')
        if not order:
            raise UserError('Receipt %s not found' % pos_reference)
        return order.get_receipt_pdf()

    # ------------------------------------------------------------------
    # Ports of order_line.js helpers
    # ------------------------------------------------------------------
    @api.model
    def _khatri_parse_product_json(self, product):
        raw = product.description or product.description_picking or product.description_sale or ''
        if not raw or not isinstance(raw, str):
            return None
        raw = html.unescape(re.sub(r'<[^>]*>', ' ', raw))
        m = re.search(r'\{[\s\S]*\}', raw)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    @api.model
    def _khatri_line_type(self, line):
        """'stepped' (Section A) or 'percentage_profit' / 'flat' / 'none' (Section B)."""
        cfg = self._khatri_parse_product_json(line.product_id)
        if not cfg or cfg.get('price_list_default') is True:
            return 'stepped'
        if isinstance(cfg.get('percentage_profit'), dict):
            return 'percentage_profit'
        if isinstance(cfg.get('flat'), dict):
            return 'flat'
        return 'none'

    def _khatri_receipt_data(self):
        self.ensure_one()
        cfg = self.config_id
        d1 = cfg.khatri_first_discount or 0.0
        use_second = cfg.khatri_enable_second_discount
        d2 = (cfg.khatri_second_discount or 0.0) if use_second else 0.0

        stepped, custom = [], []
        s_orig = s_fin = c_orig = c_fin = 0.0
        custom_pct = 0.0
        for line in self.lines:
            disc = line.discount or 0.0
            qty = line.qty or 1
            unit = line.price_unit or 0.0
            mrp = unit * qty
            fin = mrp * (1 - disc / 100.0)
            row = {
                'name': line.product_id.display_name or line.full_product_name or '',
                'qty': line.qty,
                'unit': unit,
                'mrp': mrp,
                'final': fin,
                'disc': disc,
            }
            if self._khatri_line_type(line) == 'stepped':
                stepped.append(row)
                s_orig += mrp
                s_fin += fin
            else:
                custom.append(row)
                c_orig += mrp
                c_fin += fin
                if disc > 0:
                    custom_pct = disc

        s_saved = s_orig - s_fin
        if s_saved > 0:
            heading_a = ('SECTION A : %g%% + %g%% Discount' % (d1, d2)) if (use_second and d2 > 0) \
                else ('SECTION A : %g%% Discount' % d1)
        else:
            heading_a = 'SECTION A'

        total_orig = s_orig + c_orig
        total_fin = s_fin + c_fin
        return {
            'stepped': stepped, 'custom': custom,
            'heading_a': heading_a,
            's_orig': s_orig, 's_fin': s_fin, 's_saved': s_saved,
            'c_orig': c_orig, 'c_fin': c_fin, 'c_saved': c_orig - c_fin, 'c_pct': custom_pct,
            'total_orig': total_orig, 'total_fin': total_fin, 'total_saved': total_orig - total_fin,
            'discounts': sum((l.price_unit * l.qty) * (l.discount or 0) / 100.0 for l in self.lines),
        }

    @api.model
    def _khatri_fmt(self, amount):
        return '₹ {:,.2f}'.format(amount or 0.0)

    @api.model
    def _khatri_grg_logo(self):
        try:
            with file_open(GRG_LOGO_PATH, 'rb') as f:
                return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()
        except Exception:
            return False

    @api.model
    def _khatri_grg_contact(self):
        return GRG_CONTACT

    def _khatri_upi_id(self):
        """Find the shop's UPI ID (VPA, e.g. 98xxxx@ybl).

        1. System Parameter 'khatri_pos.upi_id' (explicit override)
        2. any UPI/VPA text field on the POS config, its payment methods, or the company
           (where the POS-receipt QR module keeps it)
        3. any System Parameter whose key contains 'upi' or 'vpa'
        """
        self.ensure_one()
        vpa = re.compile(r'^[\w.\-]{2,256}@[a-zA-Z][\w.\-]{1,64}$')

        def ok(v):
            return isinstance(v, str) and vpa.match(v.strip()) and v.strip()

        ICP = self.env['ir.config_parameter'].sudo()
        val = ok(ICP.get_param('khatri_pos.upi_id'))
        if val:
            return val
        config = self.config_id.sudo()
        upi_methods = config.payment_method_ids.filtered(lambda m: 'upi' in (m.name or '').lower())
        for rec in [config] + list(upi_methods) + [self.company_id.sudo()]:
            for fname, field in rec._fields.items():
                if field.type == 'char' and ('upi' in fname or 'vpa' in fname):
                    val = ok(rec[fname])
                    if val:
                        return val
        for p in ICP.search(['|', ('key', 'ilike', 'upi'), ('key', 'ilike', 'vpa')]):
            val = ok(p.value)
            if val:
                return val
        return False

    def _khatri_upi_qr(self):
        """UPI QR for the bill amount (shown only when a UPI ID is found)."""
        upi = self._khatri_upi_id()
        if not upi:
            return False
        value = 'upi://pay?pa=%s&pn=%s&am=%.2f&cu=INR&tn=%s' % (
            upi, quote(self.company_id.name or ''), self.amount_total,
            quote(self.pos_reference or self.name or ''))
        png = None
        try:
            import io
            import qrcode
            img = qrcode.make(value, box_size=8, border=2)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            png = buf.getvalue()
        except Exception:
            try:
                png = self.env['ir.actions.report'].barcode('QR', value, width=180, height=180)
            except Exception:
                _logger.warning('khatri: could not generate UPI QR for %s', self.display_name)
                return False
        return 'data:image/png;base64,' + base64.b64encode(png).decode()
