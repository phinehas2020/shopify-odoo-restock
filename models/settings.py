# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    shopify_store_domain = fields.Char(
        string="Shopify Store Domain",
        help="e.g. mystore.myshopify.com",
    )
    shopify_access_token = fields.Char(
        string="Shopify Access Token",
        help="Admin API access token. Stored in system parameters.",
    )
    shopify_api_version = fields.Char(
        string="Shopify API Version",
        default="2023-04",
        help="e.g. 2023-04",
    )
    shopify_location_id_global = fields.Char(
        string="Shopify Location ID (Global)",
        help="e.g. gid://shopify/Location/123456789",
    )
    shopify_location_id_numeric = fields.Char(
        string="Shopify Location ID (Numeric)",
        help="e.g. 123456789",
    )

    # Recipient selection via employee dropdown
    restock_employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Alert Recipient (Employee)",
        help="Select an employee to receive restock emails.",
        domain=[],
    )
    restock_email_to = fields.Char(
        string="Derived Email",
        help="Filled automatically from the selected employee's work email.",
        readonly=True,
    )

    # Webhook posting (e.g., RSS/Logic App)
    restock_webhook_enabled = fields.Boolean(
        string="Post each item to webhook",
        help="If enabled, each restock item will be POSTed to the configured webhook URL.",
        default=False,
    )
    restock_webhook_url = fields.Char(
        string="Webhook URL",
        help="Target URL to POST each restock item as JSON (title, guid, amount).",
    )
    restock_project_id = fields.Many2one(
        comodel_name="project.project",
        string="Restock Project",
        help="Project to create Shopify restock to-do tasks in.",
    )
    restock_odoo_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Default Stock Location",
        domain=[("usage", "=", "internal")],
        help="Default Odoo stock location to deduct inventory from.",
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env["ir.config_parameter"].sudo()
        res.update(
            shopify_store_domain=ICP.get_param("odoo_shopify_restock.store_domain", default=""),
            shopify_access_token=ICP.get_param("odoo_shopify_restock.access_token", default=""),
            shopify_api_version=ICP.get_param("odoo_shopify_restock.api_version", default="2023-04"),
            shopify_location_id_global=ICP.get_param("odoo_shopify_restock.location_id_global", default=""),
            shopify_location_id_numeric=ICP.get_param("odoo_shopify_restock.location_id_numeric", default=""),
            restock_employee_id=int(ICP.get_param("odoo_shopify_restock.employee_id", default="0") or 0) or False,
            restock_email_to=ICP.get_param("odoo_shopify_restock.email_to", default=""),
            restock_webhook_enabled=ICP.get_param("odoo_shopify_restock.webhook_enabled", default="0") == "1",
            restock_webhook_url=ICP.get_param("odoo_shopify_restock.webhook_url", default=""),
            restock_project_id=int(ICP.get_param("odoo_shopify_restock.project_id", default="0") or 0) or False,
            restock_odoo_location_id=int(ICP.get_param("odoo_shopify_restock.odoo_location_id", default="0") or 0) or False,
        )
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("odoo_shopify_restock.store_domain", self.shopify_store_domain or "")
        ICP.set_param("odoo_shopify_restock.access_token", self.shopify_access_token or "")
        ICP.set_param("odoo_shopify_restock.api_version", self.shopify_api_version or "")
        ICP.set_param("odoo_shopify_restock.location_id_global", self.shopify_location_id_global or "")
        ICP.set_param("odoo_shopify_restock.location_id_numeric", self.shopify_location_id_numeric or "")
        # derive email from employee
        email = self.restock_employee_id.work_email if self.restock_employee_id else ""
        ICP.set_param("odoo_shopify_restock.employee_id", str(self.restock_employee_id.id or 0))
        ICP.set_param("odoo_shopify_restock.email_to", email)
        ICP.set_param("odoo_shopify_restock.webhook_enabled", "1" if self.restock_webhook_enabled else "0")
        ICP.set_param("odoo_shopify_restock.webhook_url", self.restock_webhook_url or "")
        ICP.set_param("odoo_shopify_restock.project_id", str(self.restock_project_id.id or 0))
        ICP.set_param("odoo_shopify_restock.odoo_location_id", str(self.restock_odoo_location_id.id or 0))
