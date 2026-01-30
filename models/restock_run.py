# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ShopifyRestockRun(models.Model):
    _name = "shopify.restock.run"
    _description = "Shopify Restock Run"
    _order = "create_date desc"

    name = fields.Char(default=lambda self: fields.Datetime.now())
    report_timestamp = fields.Datetime(string="Report Timestamp")
    total_products_found = fields.Integer(string="Total Products Found")
    total_products_checked = fields.Integer(string="Total Products Checked")
    rss_item_count = fields.Integer(string="Alert Count")
    has_restock_alerts = fields.Boolean(string="Has Restock Alerts")
    email_sent = fields.Boolean(string="Email Sent")
    email_to = fields.Char(string="Email To")
    rss_items_json = fields.Text(string="Alerts JSON", help="Serialized JSON of alert items")
    error_message = fields.Char()
    location_id = fields.Many2one(
        comodel_name="shopify.restock.location",
        string="Shopify Location",
    )

    item_ids = fields.One2many(
        comodel_name="shopify.restock.item",
        inverse_name="run_id",
        string="Items",
    )
