# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class ShopifyRestockController(http.Controller):

    @http.route('/shopify_restock/run_now', type='http', auth='user', website=False)
    def run_now(self, **kw):  # noqa: ARG002
        # Run with email and then redirect to runs
        request.env['shopify.restock.service'].run_restock_check(send_email=True)
        action = request.env.ref('odoo_shopify_restock.action_open_shopify_restock_runs').sudo().read()[0]
        # Redirect to the runs action
        return request.redirect('/web?#action=%s' % action['id'])
