# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


SCHEDULE_DAY_FIELDS = (
    "restock_schedule_monday",
    "restock_schedule_tuesday",
    "restock_schedule_wednesday",
    "restock_schedule_thursday",
    "restock_schedule_friday",
    "restock_schedule_saturday",
    "restock_schedule_sunday",
)


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

    restock_project_id = fields.Many2one(
        comodel_name="project.project",
        string="Restock Project",
        help="Project to create Shopify restock to-do tasks in.",
    )
    restock_source_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Source Location (Warehouse)",
        domain=[("usage", "=", "internal")],
        help="The warehouse location to transfer stock FROM when restock tasks are completed.",
    )
    restock_odoo_location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Destination Location (Retail)",
        domain=[("usage", "=", "internal")],
        help="Default retail/store location to transfer stock TO. Can be overridden per Shopify location.",
    )
    restock_schedule_enabled = fields.Boolean(
        string="Enable Automatic Runs",
        help="Run the Shopify restock check automatically on a weekly schedule.",
    )
    restock_schedule_employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Automatic Run Assignee",
        help="Tasks created by scheduled runs will be assigned to this employee when possible. Their work email is used for the summary email.",
    )
    restock_schedule_location_id = fields.Many2one(
        comodel_name="shopify.restock.location",
        string="Automatic Run Shopify Location",
        help="Optional location override for scheduled runs. If left blank, the default Shopify location settings are used.",
    )
    restock_schedule_time = fields.Float(
        string="Run Time",
        default=9.0,
        help="Local time for automatic runs.",
    )
    restock_schedule_timezone = fields.Char(
        string="Schedule Time Zone",
        readonly=True,
        help="Automatic runs use this time zone when checking the selected time and weekdays.",
    )
    restock_schedule_monday = fields.Boolean(string="Monday", default=True)
    restock_schedule_tuesday = fields.Boolean(string="Tuesday", default=True)
    restock_schedule_wednesday = fields.Boolean(string="Wednesday", default=True)
    restock_schedule_thursday = fields.Boolean(string="Thursday", default=True)
    restock_schedule_friday = fields.Boolean(string="Friday", default=True)
    restock_schedule_saturday = fields.Boolean(string="Saturday")
    restock_schedule_sunday = fields.Boolean(string="Sunday")

    @api.model
    def _param_as_bool(self, key, default=False):
        value = self.env["ir.config_parameter"].sudo().get_param(key)
        if value in (None, ""):
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _validate_schedule_settings(self):
        self.ensure_one()
        if not self.restock_schedule_enabled:
            return
        if not any(getattr(self, field_name) for field_name in SCHEDULE_DAY_FIELDS):
            raise ValidationError("Choose at least one weekday for automatic Shopify restock runs.")

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env["ir.config_parameter"].sudo()
        default_tz = (
            ICP.get_param("odoo_shopify_restock.schedule_timezone")
            or self.env.user.tz
            or self.env.context.get("tz")
            or "UTC"
        )
        res.update(
            shopify_store_domain=ICP.get_param("odoo_shopify_restock.store_domain", default=""),
            shopify_access_token=ICP.get_param("odoo_shopify_restock.access_token", default=""),
            shopify_api_version=ICP.get_param("odoo_shopify_restock.api_version", default="2023-04"),
            shopify_location_id_global=ICP.get_param("odoo_shopify_restock.location_id_global", default=""),
            shopify_location_id_numeric=ICP.get_param("odoo_shopify_restock.location_id_numeric", default=""),
            restock_project_id=int(ICP.get_param("odoo_shopify_restock.project_id", default="0") or 0) or False,
            restock_source_location_id=int(ICP.get_param("odoo_shopify_restock.source_location_id", default="0") or 0) or False,
            restock_odoo_location_id=int(ICP.get_param("odoo_shopify_restock.odoo_location_id", default="0") or 0) or False,
            restock_schedule_enabled=self._param_as_bool(
                "odoo_shopify_restock.schedule_enabled",
                default=False,
            ),
            restock_schedule_employee_id=int(
                ICP.get_param("odoo_shopify_restock.schedule_employee_id", default="0") or 0
            ) or False,
            restock_schedule_location_id=int(
                ICP.get_param("odoo_shopify_restock.schedule_location_id", default="0") or 0
            ) or False,
            restock_schedule_time=float(
                ICP.get_param("odoo_shopify_restock.schedule_time", default="9.0") or 9.0
            ),
            restock_schedule_timezone=default_tz,
            restock_schedule_monday=self._param_as_bool(
                "odoo_shopify_restock.schedule_monday",
                default=True,
            ),
            restock_schedule_tuesday=self._param_as_bool(
                "odoo_shopify_restock.schedule_tuesday",
                default=True,
            ),
            restock_schedule_wednesday=self._param_as_bool(
                "odoo_shopify_restock.schedule_wednesday",
                default=True,
            ),
            restock_schedule_thursday=self._param_as_bool(
                "odoo_shopify_restock.schedule_thursday",
                default=True,
            ),
            restock_schedule_friday=self._param_as_bool(
                "odoo_shopify_restock.schedule_friday",
                default=True,
            ),
            restock_schedule_saturday=self._param_as_bool(
                "odoo_shopify_restock.schedule_saturday",
                default=False,
            ),
            restock_schedule_sunday=self._param_as_bool(
                "odoo_shopify_restock.schedule_sunday",
                default=False,
            ),
        )
        return res

    def set_values(self):
        self.ensure_one()
        self._validate_schedule_settings()
        super().set_values()
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("odoo_shopify_restock.store_domain", self.shopify_store_domain or "")
        ICP.set_param("odoo_shopify_restock.access_token", self.shopify_access_token or "")
        ICP.set_param("odoo_shopify_restock.api_version", self.shopify_api_version or "")
        ICP.set_param("odoo_shopify_restock.location_id_global", self.shopify_location_id_global or "")
        ICP.set_param("odoo_shopify_restock.location_id_numeric", self.shopify_location_id_numeric or "")
        ICP.set_param("odoo_shopify_restock.project_id", str(self.restock_project_id.id or 0))
        ICP.set_param("odoo_shopify_restock.source_location_id", str(self.restock_source_location_id.id or 0))
        ICP.set_param("odoo_shopify_restock.odoo_location_id", str(self.restock_odoo_location_id.id or 0))
        ICP.set_param("odoo_shopify_restock.schedule_enabled", "1" if self.restock_schedule_enabled else "0")
        ICP.set_param("odoo_shopify_restock.schedule_employee_id", str(self.restock_schedule_employee_id.id or 0))
        ICP.set_param("odoo_shopify_restock.schedule_location_id", str(self.restock_schedule_location_id.id or 0))
        ICP.set_param("odoo_shopify_restock.schedule_time", str(self.restock_schedule_time or 0.0))
        ICP.set_param(
            "odoo_shopify_restock.schedule_timezone",
            self.env.user.tz
            or self.env.context.get("tz")
            or "UTC",
        )
        ICP.set_param("odoo_shopify_restock.schedule_owner_user_id", str(self.env.user.id or 0))
        for field_name in SCHEDULE_DAY_FIELDS:
            param_name = field_name.replace("restock_", "odoo_shopify_restock.")
            ICP.set_param(param_name, "1" if getattr(self, field_name) else "0")
        self.env["shopify.restock.service"].sudo().sync_schedule_cron()
