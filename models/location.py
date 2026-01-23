# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ShopifyRestockLocation(models.Model):
    _name = "shopify.restock.location"
    _description = "Shopify Restock Location"
    _order = "name asc"

    name = fields.Char(required=True, index=True)
    location_id_global = fields.Char(string="Shopify Location ID (Global)", required=True)
    location_id_numeric = fields.Char(string="Shopify Location ID (Numeric)")

    active = fields.Boolean(default=True)

    # Per-location webhook settings
    webhook_enabled = fields.Boolean(
        string="Post items to webhook",
        help="If enabled, items for runs using this location will be POSTed to the URL below.",
        default=False,
    )
    webhook_url = fields.Char(string="Webhook URL")

    odoo_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Odoo Stock Location",
        domain=[("usage", "=", "internal")],
        help="Optional Odoo location to deduct inventory from when restock tasks are completed.",
    )

    @api.onchange("location_id_global")
    def _onchange_global_fill_numeric(self):
        if self.location_id_global and not self.location_id_numeric:
            try:
                self.location_id_numeric = str(self.location_id_global.strip().split("/")[-1])
            except Exception:
                # Keep as is if parsing fails
                pass
