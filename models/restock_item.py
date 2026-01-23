# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class ShopifyRestockItem(models.Model):
    _name = "shopify.restock.item"
    _description = "Shopify Restock Item"
    _order = "run_id desc, id desc"

    run_id = fields.Many2one("shopify.restock.run", string="Run", required=True, ondelete="cascade")
    run_timestamp = fields.Datetime(related="run_id.report_timestamp", store=True, index=True)
    location_id = fields.Many2one(
        related="run_id.location_id",
        store=True,
        readonly=True,
    )

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

    todo_task_id = fields.Many2one(
        comodel_name="project.task",
        string="To-do Task",
        ondelete="set null",
    )
    inventory_move_id = fields.Many2one(
        comodel_name="stock.move",
        string="Inventory Move",
        ondelete="set null",
    )
    inventory_deducted = fields.Boolean(default=False, copy=False)
    inventory_deducted_at = fields.Datetime(copy=False)
    inventory_deducted_by = fields.Many2one(
        comodel_name="res.users",
        copy=False,
    )
    inventory_deduction_error = fields.Char(copy=False)

    def _get_odoo_product(self):
        self.ensure_one()
        if not self.sku:
            return None
        return self.env["product.product"].sudo().search([("default_code", "=", self.sku)], limit=1)

    def _get_source_location(self):
        self.ensure_one()
        location = None
        if self.location_id and self.location_id.odoo_location_id:
            location = self.location_id.odoo_location_id
        if not location:
            param = self.env["ir.config_parameter"].sudo().get_param("odoo_shopify_restock.odoo_location_id")
            if param and str(param).isdigit():
                location = self.env["stock.location"].sudo().browse(int(param))
        if not location:
            try:
                location = self.env.ref("stock.stock_location_stock")
            except Exception:
                location = self.env["stock.location"].sudo().search([("usage", "=", "internal")], limit=1)
        return location if location and location.exists() else None

    def _get_destination_location(self):
        self.ensure_one()
        location = None
        try:
            location = self.env.ref("stock.stock_location_inventory")
        except Exception:
            location = self.env["stock.location"].sudo().search([("usage", "=", "inventory")], limit=1)
        if not location:
            location = self.env["stock.location"].sudo().search([("usage", "=", "customer")], limit=1)
        return location if location and location.exists() else None

    def _create_inventory_move(self, product, quantity, source_location, dest_location):
        self.ensure_one()
        move_vals = {
            "name": f"Shopify Restock Deduction: {self.sku or product.display_name}",
            "product_id": product.id,
            "product_uom_qty": quantity,
            "product_uom": product.uom_id.id,
            "location_id": source_location.id,
            "location_dest_id": dest_location.id,
            "company_id": source_location.company_id.id or self.env.company.id,
            "origin": self.run_id.name or "",
            "reference": f"Shopify Restock Item {self.id}",
        }
        move = self.env["stock.move"].sudo().create(move_vals)
        move._action_confirm()
        move._action_assign()
        if hasattr(move, "_set_quantity_done"):
            move._set_quantity_done(quantity)
        elif "quantity_done" in move._fields:
            move.quantity_done = quantity
        else:
            self.env["stock.move.line"].sudo().create({
                "move_id": move.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "qty_done": quantity,
                "location_id": source_location.id,
                "location_dest_id": dest_location.id,
                "company_id": move.company_id.id,
            })
        move._action_done()
        return move

    def action_deduct_inventory(self):
        for item in self:
            if item.inventory_deducted:
                continue
            qty = int(item.restock_amount or 0)
            if qty <= 0:
                item.sudo().write({
                    "inventory_deduction_error": "No restock amount to deduct.",
                })
                continue
            product = item._get_odoo_product()
            if not product:
                item.sudo().write({
                    "inventory_deduction_error": f"No Odoo product found for SKU '{item.sku or ''}'.",
                })
                continue
            source_location = item._get_source_location()
            if not source_location:
                item.sudo().write({
                    "inventory_deduction_error": "No source stock location available for inventory deduction.",
                })
                continue
            dest_location = item._get_destination_location()
            if not dest_location:
                item.sudo().write({
                    "inventory_deduction_error": "No destination stock location available for inventory deduction.",
                })
                continue
            try:
                move = item._create_inventory_move(product, qty, source_location, dest_location)
            except Exception:
                _logger.exception("Inventory deduction failed for restock item %s", item.id)
                item.sudo().write({
                    "inventory_deduction_error": "Inventory deduction failed. See logs for details.",
                })
                continue
            deducted_by_uid = item.env.context.get("deducted_by_uid") or item.env.user.id
            item.sudo().write({
                "inventory_move_id": move.id,
                "inventory_deducted": True,
                "inventory_deducted_at": fields.Datetime.now(),
                "inventory_deducted_by": deducted_by_uid,
                "inventory_deduction_error": False,
            })
