# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _load_pos_data_fields(self, config_id):
        result = super()._load_pos_data_fields(config_id)
        for f in ["description", "description_picking", "description_sale"]:
            if f not in result:
                result.append(f)
        return result


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _load_pos_data_fields(self, config_id):
        result = super()._load_pos_data_fields(config_id)
        for f in ["description", "description_picking", "description_sale"]:
            if f not in result:
                result.append(f)
        return result
