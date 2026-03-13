# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = "project.task"

    restock_item_id = fields.Many2one(
        comodel_name="shopify.restock.item",
        string="Shopify Restock Item",
        ondelete="set null",
    )

    def _restock_task_is_done(self) -> bool:
        """Check if this task is in a 'done' state.

        Odoo 18 uses the 'state' field on project.task:
        - '01_in_progress' - In Progress (open)
        - '02_changes_requested' - Changes Requested (open)
        - '03_approved' - Approved (open)
        - '04_waiting' - Waiting (open)
        - '1_done' - Done (CLOSED and transferable)
        - '1_canceled' - Canceled (CLOSED and non-transferable)

        Falls back to stage.fold/is_closed for older versions where state is absent.
        """
        self.ensure_one()

        # Odoo 18+ uses 'state' field. Only true done should transfer inventory.
        if "state" in self._fields and self.state:
            return self.state == "1_done"

        # Fallback for older Odoo versions: check stage
        stage = self.stage_id
        if not stage:
            return False
        # In older versions, fold or is_closed indicates completion
        if "is_closed" in stage._fields:
            return bool(stage.is_closed)
        if "fold" in stage._fields:
            return bool(stage.fold)
        return False

    def write(self, vals):
        restock_tasks = self.filtered("restock_item_id")
        done_before = {task.id: task._restock_task_is_done() for task in restock_tasks}
        result = super().write(vals)
        if not restock_tasks:
            return result
        for task in restock_tasks:
            try:
                if done_before.get(task.id):
                    continue
                if not task._restock_task_is_done():
                    continue
                items = self.env["shopify.restock.item"].sudo().search([
                    ("todo_task_id", "=", task.id),
                    ("is_active_snapshot", "=", True),
                    ("inventory_transferred", "=", False),
                ])
                if (
                    not items
                    and task.restock_item_id
                    and task.restock_item_id.is_active_snapshot
                    and not task.restock_item_id.inventory_transferred
                ):
                    items = task.restock_item_id
                if not items:
                    continue
                _logger.info(
                    "Restock task %s marked done, triggering inventory transfer for items %s",
                    task.id, items.ids
                )
                items.with_context(
                    transferred_by_uid=self.env.user.id
                ).sudo().action_transfer_inventory()
            except Exception:
                _logger.exception("Failed to apply inventory transfer for restock task %s", task.id)
        return result
