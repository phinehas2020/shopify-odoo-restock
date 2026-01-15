# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ShopifyRestockItem(models.Model):
    _name = "shopify.restock.item"
    _description = "Shopify Restock Item"
    _order = "run_id desc, id desc"

    run_id = fields.Many2one("shopify.restock.run", string="Run", required=True, ondelete="cascade")
    run_timestamp = fields.Datetime(related="run_id.report_timestamp", store=True, index=True)

    product_title = fields.Char(required=True)
    variant_title = fields.Char()
    sku = fields.Char(index=True)
    product_handle = fields.Char()
    product_url = fields.Char(string="Product URL")

    current_qty = fields.Integer(string="Current Qty")
    restock_level = fields.Integer(string="Restock Level")
    restock_amount = fields.Integer(string="Recommended Order")

    urgency = fields.Selection([
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
    ], default="low", index=True)

    product_id_global = fields.Char()
    variant_id_global = fields.Char()
