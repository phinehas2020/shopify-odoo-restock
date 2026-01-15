# -*- coding: utf-8 -*-
import base64
import csv
import io

from odoo import fields, models


class ShopifyRetailInventoryWizard(models.TransientModel):
    _name = "shopify.retail.inventory.wizard"
    _description = "Shopify Retail Inventory Report"

    location_id = fields.Many2one(
        comodel_name="shopify.restock.location",
        string="Shopify Location",
        help="Select the retail location to report on (uses settings if left blank).",
    )
    report_file = fields.Binary(readonly=True)
    report_filename = fields.Char(readonly=True)
    report_row_count = fields.Integer(string="Rows", readonly=True)

    def action_generate_report(self):
        self.ensure_one()
        service = self.env["shopify.restock.service"]
        if self.location_id and self.location_id.location_id_numeric:
            ctx = dict(self.env.context, shopify_restock_location=self.location_id)
            service = service.with_context(ctx)

        result = service.generate_inventory_report()
        rows = result.get("rows", []) or []

        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Product", "Variant", "SKU", "Quantity"])
        for row in rows:
            writer.writerow([
                row.get("product_title", ""),
                row.get("variant_title", ""),
                row.get("sku", ""),
                row.get("quantity", 0),
            ])
        csv_bytes = output.getvalue().encode("utf-8")
        output.close()

        report_date = fields.Date.today().isoformat()
        location_suffix = ""
        if self.location_id and self.location_id.location_id_numeric:
            location_suffix = f"-{self.location_id.location_id_numeric}"
        filename = f"retail-inventory{location_suffix}-{report_date}.csv"

        self.write({
            "report_file": base64.b64encode(csv_bytes),
            "report_filename": filename,
            "report_row_count": len(rows),
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": "shopify.retail.inventory.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
