# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ShopifyRestockRun(models.Model):
    _name = "shopify.restock.run"
    _description = "Shopify Restock Run"
    _order = "create_date desc"

    name = fields.Char(default=lambda self: fields.Datetime.now())
    report_timestamp = fields.Datetime()
    total_products_found = fields.Integer()
    total_products_checked = fields.Integer()
    rss_item_count = fields.Integer()
    has_restock_alerts = fields.Boolean()
    email_sent = fields.Boolean()
    email_to = fields.Char()
    rss_items_json = fields.Text(help="Serialized JSON of rss_items")
    error_message = fields.Char()

    item_ids = fields.One2many(
        comodel_name="shopify.restock.item",
        inverse_name="run_id",
        string="Items",
    )
