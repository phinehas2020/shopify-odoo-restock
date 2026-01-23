# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ShopifyRestockWizard(models.TransientModel):
    _name = "shopify.restock.wizard"
    _description = "Run Shopify Restock Check"

    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Alert Recipient (Employee)",
        help="Email will be sent to this employee's work email for this run only.",
    )
    location_id = fields.Many2one(
        comodel_name="shopify.restock.location",
        string="Shopify Location",
        help="Choose which Shopify location to use for inventory checks.",
    )

    def action_run(self):
        self.ensure_one()
        service = self.env["shopify.restock.service"]
        email_to = (self.employee_id.work_email or "").strip() if self.employee_id else ""
        # If a location is selected, pass it in context for the service to use
        ctx_employee = {}
        if self.employee_id:
            ctx_employee["restock_employee_id"] = self.employee_id.id
            if self.employee_id.user_id:
                ctx_employee["restock_user_id"] = self.employee_id.user_id.id
        if self.location_id and self.location_id.location_id_numeric:
            # Pass location in context so service can use per-location settings
            ctx = dict(self.env.context, shopify_restock_location=self.location_id, **ctx_employee)
            service = service.with_context(ctx)
            service.run_restock_check(send_email=bool(email_to), email_to_override=email_to)
        else:
            if ctx_employee:
                service = service.with_context(dict(self.env.context, **ctx_employee))
            service.run_restock_check(send_email=bool(email_to), email_to_override=email_to)
        action = self.env.ref("odoo_shopify_restock.action_open_shopify_restock_runs").sudo().read()[0]
        return action
