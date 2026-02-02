# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Fix timeline view errors in Project module after installation."""
    _logger.info("Running post-init hook to fix timeline view issues")
    _fix_timeline_views(env)


def post_load_hook():
    """Called after module is loaded."""
    pass


def _fix_timeline_views(env):
    """Remove timeline from view_mode if timeline view doesn't exist."""
    action_model = env["ir.actions.act_window"].sudo()
    view_model = env["ir.ui.view"].sudo()

    # Find all project-related actions that reference timeline
    actions = action_model.search([
        ("view_mode", "ilike", "timeline"),
        ("res_model", "ilike", "project."),
    ])

    for action in actions:
        modes = [m.strip() for m in (action.view_mode or "").split(",") if m.strip()]
        if not modes:
            continue

        # Check if timeline view actually exists for this model
        has_timeline_view = bool(view_model.search([
            ("model", "=", action.res_model),
            ("type", "=", "timeline"),
        ], limit=1))

        if not has_timeline_view:
            # Remove timeline from modes
            new_modes = [m for m in modes if m != "timeline"]
            if not new_modes:
                new_modes = ["kanban", "tree", "form"]

            # Deduplicate while preserving order
            seen = set()
            normalized = []
            for mode in new_modes:
                if mode not in seen:
                    seen.add(mode)
                    normalized.append(mode)

            _logger.info(
                "Fixing action %s: removing timeline view (was: %s, now: %s)",
                action.name, action.view_mode, ",".join(normalized)
            )
            action.write({"view_mode": ",".join(normalized)})
        elif modes[0] == "timeline" and len(modes) > 1:
            # Timeline exists but shouldn't be default - move it to end
            new_modes = [m for m in modes if m != "timeline"] + ["timeline"]
            seen = set()
            normalized = []
            for mode in new_modes:
                if mode not in seen:
                    seen.add(mode)
                    normalized.append(mode)

            _logger.info(
                "Fixing action %s: moving timeline to end (was: %s, now: %s)",
                action.name, action.view_mode, ",".join(normalized)
            )
            action.write({"view_mode": ",".join(normalized)})
