# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    khatri_receipt_logo = fields.Image(
        string='Receipt Logo',
        max_width=1024, max_height=1024,
        help='Logo printed on POS receipts. If empty, the company logo is used.',
    )
    khatri_receipt_logo_key = fields.Char(compute='_compute_khatri_receipt_logo_key')

    @api.depends('khatri_receipt_logo')
    def _compute_khatri_receipt_logo_key(self):
        # non-empty only when a receipt logo is set; also used as image cache-buster in POS
        for rec in self:
            rec.khatri_receipt_logo_key = fields.Datetime.to_string(rec.write_date or fields.Datetime.now()) \
                if rec.khatri_receipt_logo else False

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['khatri_receipt_logo_key']

    def _khatri_receipt_logo_image(self):
        """Receipt logo if uploaded, else company logo (binary, base64)."""
        self.ensure_one()
        return self.khatri_receipt_logo or self.logo
