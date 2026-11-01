# -*- coding: utf-8 -*-
import base64

from odoo import http
from odoo.http import request


class KhatriReceiptPdf(http.Controller):

    # GET /pos-module/receipt/<order_id>.pdf   (add ?download=1 to force download)
    # Header: Authorization: Bearer <ODOO_API_KEY>
    @http.route('/pos-module/receipt/<int:order_id>.pdf', type='http', auth='bearer',
                methods=['GET'], csrf=False, readonly=True)
    def khatri_receipt_pdf(self, order_id, download=None, **kw):
        order = request.env['pos.order'].browse(order_id).exists()
        if not order:
            return request.not_found()
        data = order.get_receipt_pdf()
        pdf = base64.b64decode(data['pdf_base64'])
        disposition = 'attachment' if download else 'inline'
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', str(len(pdf))),
            ('Content-Disposition', '%s; filename="%s"' % (disposition, data['filename'])),
        ])
