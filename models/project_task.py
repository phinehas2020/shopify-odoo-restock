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
        self.ensure_one()
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
                task.restock_item_id.with_context(
                    deducted_by_uid=self.env.user.id
                ).sudo().action_deduct_inventory()
            except Exception:
                _logger.exception("Failed to apply inventory deduction for restock task %s", task.id)
        return result
