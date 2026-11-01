# -*- coding: utf-8 -*-
"""Mobile-app APIs for khatri_pos_discount.

Same discount rules as the POS web app (static/src/js/order_line.js):
  - product description JSON {"flat": {"discount": X}} / {"percentage_profit": {...}}
    -> custom discount (Section B)
  - no JSON / {"price_list_default": true} -> stepped discount from POS settings
    (50% + 25% => 62.5%) (Section A)
  - the same product scanned twice is merged into one line

JSON-RPC (execute_kw on model pos.order, args=[], kwargs=...):
  khatri_cart(items, config_id=None, partner_id=None)          -> cart preview, nothing saved
  khatri_sell(items, config_id=None, payment_method=None, payments=None,
              partner_id=None, customer_phone=None, customer_name=None,
              uuid=None, note=None, return_pdf=False)            -> creates a PAID pos.order

items: ["8901234567890", "8901234567890", ...]          (each scan = qty 1)
   or  [{"barcode": "8901234567890", "qty": 2}, ...]
"""
from datetime import datetime

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError
from odoo.tools import float_round, float_is_zero


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _khatri_get_session(self, config_id=None):
        domain = [('state', '=', 'opened'), ('config_id.company_id', 'in', self.env.companies.ids)]
        if config_id:
            domain.append(('config_id', '=', int(config_id)))
        session = self.env['pos.session'].search(domain, limit=1, order='id desc')
        if not session:
            raise UserError(_('No open POS session%s. Open the POS session in Odoo first.') %
                            (' for POS config %s' % config_id if config_id else ''))
        return session

    @api.model
    def _khatri_config_for_preview(self, config_id=None):
        """Cart preview works with an open session if there is one, else just the config."""
        session = self.env['pos.session'].search(
            [('state', '=', 'opened'), ('config_id', '=', int(config_id))] if config_id else
            [('state', '=', 'opened'), ('config_id.company_id', 'in', self.env.companies.ids)],
            limit=1, order='id desc')
        if session:
            return session.config_id, session
        if not config_id:
            raise UserError(_('No open POS session. Pass config_id or open a POS session.'))
        config = self.env['pos.config'].browse(int(config_id)).exists()
        if not config:
            raise UserError(_('POS config %s not found.') % config_id)
        return config, self.env['pos.session']

    @api.model
    def _khatri_normalize_items(self, items):
        """-> ordered list of (code, qty), same code merged."""
        if isinstance(items, (str, int)):
            items = [items]
        merged = {}
        for it in items or []:
            if isinstance(it, dict):
                code = str(it.get('barcode') or it.get('code') or '').strip()
                qty = float(it.get('qty') or it.get('quantity') or 1)
            else:
                code, qty = str(it).strip(), 1.0
            if code:
                merged[code] = merged.get(code, 0.0) + qty
        return list(merged.items())

    @api.model
    def _khatri_find_product(self, code):
        Product = self.env['product.product']
        product = Product.search([('barcode', '=', code)], limit=1) \
            or Product.search([('default_code', '=', code)], limit=1)
        if not product:
            return Product, 'not_found'
        if not product.sale_ok:
            return product, 'not_for_sale'
        if not product.available_in_pos:
            return product, 'not_available_in_pos'
        return product, False

    @api.model
    def _khatri_stepped_effective(self, config):
        # port of getSteppedEffective()
        if not config.khatri_enable_stepped_discount:
            return 0.0
        d1 = config.khatri_first_discount or 0.0
        use_second = config.khatri_enable_second_discount
        d2 = (config.khatri_second_discount or 0.0) if use_second else 0.0
        if use_second and d2 > 0:
            return 100.0 * (1 - (1 - d1 / 100.0) * (1 - d2 / 100.0))
        return d1

    @api.model
    def _khatri_resolve_discount(self, product, config):
        # port of resolveLineDiscount() -> (discount_pct, type)
        stepped = self._khatri_stepped_effective(config)
        cfg = self._khatri_parse_product_json(product)
        if not cfg or cfg.get('price_list_default') is True:
            return stepped, 'stepped'
        if isinstance(cfg.get('percentage_profit'), dict):
            try:
                return float(cfg['percentage_profit'].get('discount') or 0), 'percentage_profit'
            except (TypeError, ValueError):
                return 0.0, 'percentage_profit'
        if isinstance(cfg.get('flat'), dict):
            try:
                return float(cfg['flat'].get('discount') or 0), 'flat'
            except (TypeError, ValueError):
                return 0.0, 'flat'
        return 0.0, 'none'

    @api.model
    def _khatri_section_a_heading(self, config, saved):
        if not saved > 0:
            return 'SECTION A'
        d1 = config.khatri_first_discount or 0.0
        d2 = config.khatri_second_discount or 0.0
        if config.khatri_enable_second_discount and d2 > 0:
            return 'SECTION A : %g%% + %g%% Discount' % (d1, d2)
        return 'SECTION A : %g%% Discount' % d1

    @api.model
    def _khatri_build_cart(self, items, config, partner=None):
        """Price + discount + tax for each line, exactly as the POS line would get."""
        AccountTax = self.env['account.tax']
        company = config.company_id
        currency = config.currency_id
        pricelist = config.pricelist_id
        fpos = config.default_fiscal_position_id
        partner = partner or self.env['res.partner']

        lines, unknown = [], []
        for code, qty in self._khatri_normalize_items(items):
            product, err = self._khatri_find_product(code)
            if err:
                unknown.append({'barcode': code, 'reason': err,
                                'product': product.display_name if product else None})
                continue
            existing = next((l for l in lines if l['product_id'] == product.id), None)
            if existing:  # same product with barcode + internal ref -> still one line
                existing['qty'] += qty
                continue
            lines.append({'product_id': product.id, 'barcode': product.barcode or code, 'qty': qty,
                          '_product': product})

        for idx, l in enumerate(lines, 1):
            product = l.pop('_product')
            qty = l['qty']
            taxes = product.taxes_id.filtered_domain(AccountTax._check_company_domain(company))
            mapped = fpos.map_tax(taxes) if fpos else taxes
            price = pricelist._get_product_price(product, qty, currency=currency) if pricelist else product.lst_price
            price = AccountTax._fix_tax_included_price_company(price, taxes, mapped, company)
            disc, dtype = self._khatri_resolve_discount(product, config)
            unit_final = price * (1 - disc / 100.0)
            res = mapped.compute_all(unit_final, currency, qty, product=product, partner=partner)
            mrp_total = price * qty
            l.update({
                'line_no': idx,
                'name': product.display_name,
                'default_code': product.default_code or '',
                'section': 'A' if dtype == 'stepped' else 'B',
                'discount_type': dtype,
                'discount_pct': round(disc, 4),
                'unit_mrp': currency.round(price),
                'unit_final': currency.round(unit_final),
                'mrp_total': currency.round(mrp_total),
                'discount_amount': currency.round(mrp_total * disc / 100.0),
                'price_subtotal': res['total_excluded'],
                'price_subtotal_incl': res['total_included'],
                'final': currency.round(mrp_total * (1 - disc / 100.0)),   # as on receipt
                'amount': currency.round(res['total_included']),           # payable incl. tax
                'tax': currency.round(res['total_included'] - res['total_excluded']),
                'tax_ids': taxes.ids,
                'taxes': mapped.mapped('name'),
            })

        def _sum(rows, key):
            return currency.round(sum(r[key] for r in rows))

        sec_a = [l for l in lines if l['section'] == 'A']
        sec_b = [l for l in lines if l['section'] == 'B']
        a_mrp, a_fin = _sum(sec_a, 'mrp_total'), _sum(sec_a, 'final')
        b_mrp, b_fin = _sum(sec_b, 'mrp_total'), _sum(sec_b, 'final')
        mrp_total, final = _sum(lines, 'mrp_total'), _sum(lines, 'final')
        total = _sum(lines, 'amount')
        return {
            'config_id': config.id,
            'config_name': config.name,
            'currency': currency.name,
            'lines': lines,
            'unknown_barcodes': unknown,
            'section_a': {'heading': self._khatri_section_a_heading(config, a_mrp - a_fin),
                          'count': len(sec_a), 'mrp_total': a_mrp,
                          'discount': currency.round(a_mrp - a_fin), 'total': a_fin},
            'section_b': {'heading': 'SECTION B : Special Discount' if b_mrp - b_fin > 0 else 'SECTION B',
                          'count': len(sec_b), 'mrp_total': b_mrp,
                          'discount': currency.round(b_mrp - b_fin), 'total': b_fin},
            'totals': {
                'item_count': len(lines),
                'total_qty': sum(l['qty'] for l in lines),
                'mrp_total': mrp_total,
                'total_saved': currency.round(mrp_total - final),
                'tax': _sum(lines, 'tax'),
                'total': total,
            },
        }

    @api.model
    def _khatri_find_partner(self, partner_id=None, customer_phone=None, customer_name=None):
        Partner = self.env['res.partner']
        if partner_id:
            return Partner.browse(int(partner_id)).exists()
        if customer_phone:
            digits = ''.join(c for c in str(customer_phone) if c.isdigit())[-10:]
            if digits:
                partner = Partner.search([('phone', 'ilike', digits)], limit=1)
                if partner:
                    return partner
                if customer_name:
                    return Partner.create({'name': customer_name, 'phone': customer_phone})
        return Partner

    @api.model
    def _khatri_find_payment_method(self, config, method):
        methods = config.payment_method_ids
        if not methods:
            raise UserError(_('POS %s has no payment methods.') % config.name)
        if method in (None, '', False):
            return methods[:1]
        if isinstance(method, int) or str(method).isdigit():
            pm = methods.filtered(lambda m: m.id == int(method))
        else:
            name = str(method).strip().lower()
            pm = methods.filtered(lambda m: m.name.strip().lower() == name) \
                or methods.filtered(lambda m: name in m.name.lower())
        if not pm:
            raise UserError(_('Payment method "%s" not found in POS %s. Available: %s') %
                            (method, config.name, ', '.join(methods.mapped('name'))))
        return pm[:1]

    def _khatri_sell_result(self, return_pdf=False, cart=None):
        self.ensure_one()
        res = {
            'order_id': self.id,
            'name': self.name,
            'pos_reference': self.pos_reference,
            'state': self.state,
            'date_order': fields.Datetime.to_string(self.date_order),
            'amount_total': self.amount_total,
            'amount_tax': self.amount_tax,
            'amount_paid': self.amount_paid,
            'change': self.amount_return,
            'payments': [{'method': p.payment_method_id.name, 'amount': p.amount}
                         for p in self.payment_ids],
            'receipt_pdf_url': '/pos-module/receipt/%s.pdf' % self.id,
        }
        if cart is not None:
            res['cart'] = cart
        if return_pdf:
            res['pdf_base64'] = self.get_receipt_pdf()['pdf_base64']
        return res

    # ------------------------------------------------------------------
    # API 1: cart preview (scan -> list with discounts). Saves nothing.
    # ------------------------------------------------------------------
    @api.model
    def khatri_cart(self, items, config_id=None, partner_id=None, customer_phone=None):
        config, _session = self._khatri_config_for_preview(config_id)
        partner = self._khatri_find_partner(partner_id, customer_phone)
        return self._khatri_build_cart(items, config, partner)

    # ------------------------------------------------------------------
    # API 2: sell (creates a PAID pos.order in the open session, like POS web)
    # ------------------------------------------------------------------
    @api.model
    def khatri_sell(self, items, config_id=None, payment_method=None, payments=None,
                    partner_id=None, customer_phone=None, customer_name=None,
                    uuid=None, note=None, return_pdf=False):
        # idempotent retry: same uuid -> same order, never a duplicate sale
        if uuid:
            existing = self.search([('uuid', '=', uuid)], limit=1)
            if existing:
                return existing._khatri_sell_result(return_pdf)

        session = self._khatri_get_session(config_id)
        config = session.config_id
        company = config.company_id
        currency = config.currency_id
        partner = self._khatri_find_partner(partner_id, customer_phone, customer_name)

        cart = self._khatri_build_cart(items, config, partner)
        if cart['unknown_barcodes']:
            raise UserError(_('Cannot sell, invalid barcodes: %s') %
                            ', '.join('%s (%s)' % (u['barcode'], u['reason']) for u in cart['unknown_barcodes']))
        if not cart['lines']:
            raise UserError(_('Cart is empty.'))

        vals = {
            'session_id': session.id,
            'company_id': company.id,
            'user_id': self.env.uid,
            'partner_id': partner.id or False,
            'pricelist_id': config.pricelist_id.id or False,
            'fiscal_position_id': config.default_fiscal_position_id.id or False,
            'date_order': fields.Datetime.now(),
            'source': 'pos',
            'amount_tax': cart['totals']['tax'],
            'amount_total': cart['totals']['total'],
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [Command.create({
                'product_id': l['product_id'],
                'full_product_name': l['name'],
                'qty': l['qty'],
                'price_unit': l['unit_mrp'],
                'discount': l['discount_pct'],
                'tax_ids': [Command.set(l['tax_ids'])],
                'price_subtotal': l['price_subtotal'],
                'price_subtotal_incl': l['price_subtotal_incl'],
            }) for l in cart['lines']],
        }
        if uuid:
            vals['uuid'] = uuid
        if note:
            vals['general_customer_note'] = note

        order = self.with_company(company).create(vals)
        order._compute_prices()  # authoritative totals (same tax engine as POS)

        # ---- payments ----
        total = order.amount_total
        if payments:
            pay_rows = [(self._khatri_find_payment_method(config, p.get('method') or p.get('payment_method')),
                         float(p.get('amount') or 0), p.get('ref')) for p in payments]
        else:
            pm = self._khatri_find_payment_method(config, payment_method)
            pay_rows = [(pm, None, None)]

        uses_cash = any(pm.is_cash_count for pm, _a, _r in pay_rows)
        due = total
        if config.cash_rounding and config.rounding_method and \
                (not config.only_round_cash_method or uses_cash):
            due = float_round(total, precision_rounding=config.rounding_method.rounding,
                              rounding_method=config.rounding_method.rounding_method)
        if len(pay_rows) == 1 and pay_rows[0][1] is None:
            pay_rows = [(pay_rows[0][0], due, None)]

        paid = sum(a for _p, a, _r in pay_rows)
        prec = currency.rounding
        if float_round(paid - due, precision_rounding=prec) < 0 and \
                not float_is_zero(paid - due, precision_rounding=prec):
            raise UserError(_('Payment %.2f is less than bill total %.2f.') % (paid, due))

        for pm, amount, ref in pay_rows:
            order.add_payment({
                'pos_order_id': order.id,
                'payment_method_id': pm.id,
                'amount': amount,
                'payment_date': fields.Datetime.now(),
                'payment_ref_no': ref or False,
            })

        change = currency.round(paid - due)
        if change > 0:
            cash_pm = session.payment_method_ids.filtered('is_cash_count')[:1]
            if not cash_pm:
                raise UserError(_('Overpayment of %.2f but no cash method to return change.') % change)
            order.add_payment({
                'name': _('return'),
                'pos_order_id': order.id,
                'payment_method_id': cash_pm.id,
                'amount': -change,
                'payment_date': fields.Datetime.now(),
                'is_change': True,
            })

        order._compute_prices()
        # same finalisation as POS web (_process_order -> _process_saved_order):
        # mark paid, create stock picking, compute cost, invoice if requested
        order._process_saved_order(False)

        try:
            order._ensure_access_token()
            config.notify_synchronisation(session.id, 0)
        except Exception:
            pass

        return order._khatri_sell_result(return_pdf, cart)
