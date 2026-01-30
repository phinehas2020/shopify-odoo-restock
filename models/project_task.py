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
        - '1_done' - Done (CLOSED)
        - '1_canceled' - Canceled (CLOSED)

        Falls back to stage.fold for older versions.
        """
        self.ensure_one()

        # Odoo 18+ uses 'state' field - closed states start with '1_'
        if "state" in self._fields and self.state:
            # Closed states: '1_done', '1_canceled'
            if self.state in ('1_done', '1_canceled'):
                return True
            # If state exists and is an open state, task is NOT done
            if self.state in ('01_in_progress', '02_changes_requested', '03_approved', '04_waiting'):
                return False

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
                _logger.info(
                    "Restock task %s marked done, triggering inventory transfer for item %s",
                    task.id, task.restock_item_id.id
                )
                task.restock_item_id.with_context(
                    transferred_by_uid=self.env.user.id
                ).sudo().action_transfer_inventory()
            except Exception:
                _logger.exception("Failed to apply inventory transfer for restock task %s", task.id)
        return result
