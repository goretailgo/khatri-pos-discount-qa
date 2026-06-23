# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_khatri_enable_stepped_discount = fields.Boolean(
        related='pos_config_id.khatri_enable_stepped_discount',
        readonly=False,
        string='Enable Stepped Discount',
    )
    pos_khatri_first_discount = fields.Float(
        related='pos_config_id.khatri_first_discount',
        readonly=False,
        string='First Discount (%)',
    )
    pos_khatri_enable_second_discount = fields.Boolean(
        related='pos_config_id.khatri_enable_second_discount',
        readonly=False,
        string='Enable Second Stepped Discount',
    )
    pos_khatri_second_discount = fields.Float(
        related='pos_config_id.khatri_second_discount',
        readonly=False,
        string='Second Discount on Remainder (%)',
    )
    pos_khatri_receipt_logo = fields.Binary(
        related='pos_config_id.khatri_receipt_logo',
        readonly=False,
        string='Receipt Footer Logo',
    )
    pos_khatri_receipt_contact = fields.Char(
        related='pos_config_id.khatri_receipt_contact',
        readonly=False,
        string='Receipt Footer Contact Number',
    )

class PosConfig(models.Model):
    _inherit = 'pos.config'

    khatri_enable_stepped_discount = fields.Boolean(
        string='Enable Stepped Discount',
        default=True,
    )
    khatri_first_discount = fields.Float(
        string='First Discount (%)',
        default=50.0,
    )
    khatri_enable_second_discount = fields.Boolean(
        string='Enable Second Stepped Discount',
        default=True,
    )
    khatri_second_discount = fields.Float(
        string='Second Discount on Remainder (%)',
        default=25.0,
    )
    khatri_receipt_logo = fields.Binary(
        string='Receipt Footer Logo',
        attachment=False,
        help='Logo image shown at the bottom of POS receipts (e.g. company branding).',
    )
    khatri_receipt_contact = fields.Char(
        string='Receipt Footer Contact Number',
        help='Contact number shown at the bottom of POS receipts.',
    )
