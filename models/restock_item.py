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
    task_state = fields.Char(
        string="Task Status",
        compute="_compute_task_state",
        store=False,
    )
    inventory_move_id = fields.Many2one(
        comodel_name="stock.move",
        string="Inventory Move",
        ondelete="set null",
    )
    inventory_transferred = fields.Boolean(string="Inventory Transferred", default=False, copy=False)
    inventory_transferred_at = fields.Datetime(copy=False)
    inventory_transferred_by = fields.Many2one(
        comodel_name="res.users",
        string="Transferred By",
        copy=False,
    )
    inventory_transfer_error = fields.Char(string="Transfer Error", copy=False)

    @api.depends("todo_task_id", "todo_task_id.state", "todo_task_id.stage_id")
    def _compute_task_state(self):
        for item in self:
            if not item.todo_task_id:
                item.task_state = "No Task"
            elif "state" in item.todo_task_id._fields and item.todo_task_id.state:
                item.task_state = item.todo_task_id.state
            elif item.todo_task_id.stage_id:
                item.task_state = item.todo_task_id.stage_id.name
            else:
                item.task_state = "Unknown"

    def _get_odoo_product(self):
        self.ensure_one()
        if not self.sku:
            return None
        return self.env["product.product"].sudo().search([("default_code", "=", self.sku)], limit=1)

    def _get_source_location(self):
        """Get the source location (warehouse where stock comes FROM)."""
        self.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()

        # First check for configured source/warehouse location
        source_param = ICP.get_param("odoo_shopify_restock.source_location_id")
        if source_param and str(source_param).isdigit():
            location = self.env["stock.location"].sudo().browse(int(source_param))
            if location.exists():
                return location

        # Fall back to main stock location
        try:
            return self.env.ref("stock.stock_location_stock")
        except Exception:
            return self.env["stock.location"].sudo().search([("usage", "=", "internal")], limit=1)

    def _get_destination_location(self):
        """Get the destination location (retail location where stock goes TO).

        This is the location being restocked - typically a retail store location.
        """
        self.ensure_one()

        # The Shopify location's linked Odoo location IS the destination
        # (this is the retail/store location that needs restocking)
        if self.location_id and self.location_id.odoo_location_id:
            return self.location_id.odoo_location_id

        # Fall back to global destination setting
        param = self.env["ir.config_parameter"].sudo().get_param(
            "odoo_shopify_restock.odoo_location_id"
        )
        if param and str(param).isdigit():
            location = self.env["stock.location"].sudo().browse(int(param))
            if location.exists():
                return location

        return None

    def _create_inventory_move(self, product, quantity, source_location, dest_location):
        """Create a stock move to transfer inventory from source to destination."""
        self.ensure_one()
        move_vals = {
            "name": f"Restock Transfer: {self.product_title} ({self.sku or product.display_name})",
            "product_id": product.id,
            "product_uom_qty": quantity,
            "product_uom": product.uom_id.id,
            "location_id": source_location.id,
            "location_dest_id": dest_location.id,
            "company_id": source_location.company_id.id or self.env.company.id,
            "origin": self.run_id.name or "",
            "reference": f"Restock: {self.product_title}",
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

    def action_transfer_inventory(self):
        """Transfer inventory from warehouse to retail location when restock task is completed."""
        for item in self:
            if item.inventory_transferred:
                _logger.debug("Item %s already transferred, skipping", item.id)
                continue
            qty = int(item.restock_amount or 0)
            if qty <= 0:
                item.sudo().write({
                    "inventory_transfer_error": "No restock amount to transfer.",
                })
                _logger.warning("Restock item %s has no quantity to transfer", item.id)
                continue
            product = item._get_odoo_product()
            if not product:
                item.sudo().write({
                    "inventory_transfer_error": f"No Odoo product found for SKU '{item.sku or ''}'.",
                })
                _logger.warning("No Odoo product found for SKU '%s' (item %s)", item.sku, item.id)
                continue
            source_location = item._get_source_location()
            if not source_location:
                item.sudo().write({
                    "inventory_transfer_error": "No source location (warehouse) configured. Set Source Location in Shopify Restock settings.",
                })
                _logger.error("No source location configured for restock item %s", item.id)
                continue
            dest_location = item._get_destination_location()
            if not dest_location:
                item.sudo().write({
                    "inventory_transfer_error": "No destination location (retail) configured. Link Odoo location to Shopify location or set in settings.",
                })
                _logger.error("No destination location configured for restock item %s", item.id)
                continue
            try:
                _logger.info(
                    "Transferring %s units of %s from %s to %s",
                    qty, product.display_name, source_location.complete_name, dest_location.complete_name
                )
                move = item._create_inventory_move(product, qty, source_location, dest_location)
            except Exception as e:
                _logger.exception("Inventory transfer failed for restock item %s", item.id)
                item.sudo().write({
                    "inventory_transfer_error": f"Transfer failed: {str(e)[:200]}",
                })
                continue
            transferred_by_uid = item.env.context.get("transferred_by_uid") or item.env.user.id
            item.sudo().write({
                "inventory_move_id": move.id,
                "inventory_transferred": True,
                "inventory_transferred_at": fields.Datetime.now(),
                "inventory_transferred_by": transferred_by_uid,
                "inventory_transfer_error": False,
            })
            _logger.info("Successfully transferred inventory for restock item %s (move %s)", item.id, move.id)
