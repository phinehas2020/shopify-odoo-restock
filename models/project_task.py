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

        Handles both:
        - Odoo 18 Todo app: uses 'state' field with values like '1_done', 'done'
        - Projects app: uses stage_id with is_closed or fold flags
        """
        self.ensure_one()

        # Odoo 18 Todo app uses 'state' field
        if "state" in self._fields and self.state:
            done_states = ['1_done', 'done', '1_canceled', 'canceled', '03_approved']
            if self.state in done_states:
                return True

        # Projects app uses stage-based completion
        stage = self.stage_id
        if not stage:
            return False
        if "is_closed" in stage._fields:
            return bool(stage.is_closed)
        return bool(stage.fold)

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
