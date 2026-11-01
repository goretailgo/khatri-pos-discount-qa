# -*- coding: utf-8 -*-
"""REST wrappers (API key as Bearer token) around pos.order.khatri_cart / khatri_sell.

POST /pos-module/api/cart   body: {"items": [...], "config_id": 1}
POST /pos-module/api/sell   body: {"items": [...], "config_id": 1, "payment_method": "UPI", ...}
"""
import json
import logging

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

CART_KEYS = ('items', 'config_id', 'partner_id', 'customer_phone')
SELL_KEYS = ('items', 'config_id', 'payment_method', 'payments', 'partner_id', 'customer_phone',
             'customer_name', 'uuid', 'note', 'return_pdf')


def _json(data, status=200):
    return request.make_response(json.dumps(data, default=str), status=status,
                                 headers=[('Content-Type', 'application/json')])


def _body():
    try:
        return json.loads(request.httprequest.get_data() or b'{}')
    except ValueError:
        raise UserError('Body must be valid JSON')


class KhatriPosApi(http.Controller):

    def _run(self, method, keys):
        try:
            body = _body()
            kwargs = {k: body[k] for k in keys if k in body}
            if 'items' not in kwargs:
                raise UserError('"items" is required')
            # savepoint: on any error nothing of the sale is kept
            with request.env.cr.savepoint():
                result = getattr(request.env['pos.order'], method)(**kwargs)
            return _json({'ok': True, 'result': result})
        except (UserError, ValidationError, AccessError) as e:
            return _json({'ok': False, 'error': str(e.args[0] if e.args else e)}, 400)
        except Exception as e:
            _logger.exception('khatri %s failed', method)
            return _json({'ok': False, 'error': str(e)}, 500)

    @http.route('/pos-module/api/cart', type='http', auth='bearer', methods=['POST'], csrf=False)
    def khatri_api_cart(self, **kw):
        return self._run('khatri_cart', CART_KEYS)

    @http.route('/pos-module/api/sell', type='http', auth='bearer', methods=['POST'], csrf=False)
    def khatri_api_sell(self, **kw):
        return self._run('khatri_sell', SELL_KEYS)
