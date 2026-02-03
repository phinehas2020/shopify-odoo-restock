# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class ShopifyRestockService(models.AbstractModel):
    _name = "shopify.restock.service"
    _description = "Shopify Restock Service"

    def _compute_needed_qty(self, item: models.Model) -> int:
        restock_qty = int(item.restock_amount or 0)
        if restock_qty <= 0 and item.restock_level is not None and item.current_qty is not None:
            try:
                restock_qty = int(item.restock_level) - int(item.current_qty)
            except (TypeError, ValueError):
                restock_qty = 0
        return max(restock_qty, 0)

    def _build_task_title(self, item: models.Model, restock_qty: int) -> str:
        display_title = item.product_title or "Restock Item"
        if item.variant_title and item.variant_title != "Default Title":
            display_title += f" - {item.variant_title}"
        return f"{display_title} | {restock_qty}"

    # ---------------------------
    # Public entrypoints
    # ---------------------------
    @api.model
    def run_restock_check(self, send_email: bool = True, email_to_override: str | None = None) -> Dict[str, Any]:
        service = self
        if not service.env.context.get("restock_run_by_uid"):
            service = service.with_context(restock_run_by_uid=service.env.user.id)
        return service.sudo()._run_restock_check_internal(
            send_email=send_email,
            email_to_override=email_to_override,
        )

    def _run_restock_check_internal(self, send_email: bool = True, email_to_override: str | None = None) -> Dict[str, Any]:
        settings = self._load_settings()
        result: Dict[str, Any]
        email_to_override = (email_to_override or "").strip() or None
        actual_email_to = email_to_override or settings.get("email_to")
        location = self.env.context.get("shopify_restock_location")
        try:
            result = self._generate_report(settings)
        except Exception as exc:  # pylint: disable=broad-except
            result = {"error": str(exc), "rss_items": [], "rss_item_count": 0, "has_restock_alerts": False}

        email_sent = False
        if send_email:
            try:
                # allow per-run override
                if email_to_override:
                    tmp_settings = dict(settings)
                    tmp_settings["email_to"] = email_to_override
                    self._send_summary_email(tmp_settings, result)
                else:
                    self._send_summary_email(settings, result)
                email_sent = True
            except Exception:  # pylint: disable=broad-except
                email_sent = False

        # persist run and items
        run = self.env["shopify.restock.run"].sudo().create({
            "report_timestamp": fields.Datetime.now(),
            "total_products_found": result.get("total_products_found", 0),
            "total_products_checked": result.get("total_products_checked", 0),
            "rss_item_count": result.get("rss_item_count", 0),
            "has_restock_alerts": result.get("has_restock_alerts", False),
            "email_sent": email_sent,
            "email_to": actual_email_to,
            "rss_items_json": json.dumps(result.get("rss_items", []), ensure_ascii=False),
            "error_message": result.get("error"),
            "location_id": location.id if location else False,
        })
        items_vals = []
        for item in result.get("rss_items", []) or []:
            items_vals.append({
                "run_id": run.id,
                "product_title": item.get("product_title"),
                "variant_title": item.get("variant_title"),
                "sku": item.get("sku"),
                "product_handle": item.get("product_handle"),
                "product_url": item.get("link"),
                "current_qty": item.get("current_qty"),
                "restock_level": item.get("restock_level"),
                "restock_amount": item.get("restock_amount"),
                "urgency": item.get("urgency") or "low",
                "product_id_global": item.get("product_id"),
                "variant_id_global": item.get("variant_id"),
            })
        if items_vals:
            items = self.env["shopify.restock.item"].sudo().create(items_vals)
            self._create_tasks_for_items(settings, items, run, location)
        return result

    @api.model
    def generate_inventory_report(self) -> Dict[str, Any]:
        return self.sudo()._generate_inventory_report_internal()

    def _generate_inventory_report_internal(self) -> Dict[str, Any]:
        settings = self._load_settings()
        required = ["store_domain", "access_token", "api_version", "location_id_numeric"]
        for key in required:
            if not settings.get(key):
                raise ValueError(f"Missing configuration: {key}")

        products = self._fetch_all_products(settings)

        inventory_item_ids: List[str] = []
        for product in products:
            product_node = product.get("node", {})
            for variant in (product_node.get("variants") or {}).get("edges", []) or []:
                v_node = variant.get("node", {})
                inv_item = v_node.get("inventoryItem")
                if inv_item and inv_item.get("id"):
                    inventory_item_ids.append(inv_item["id"])

        inventory_levels_map = self._fetch_inventory_levels_for_items(settings, inventory_item_ids)

        rows: List[Dict[str, Any]] = []
        for product in products:
            product_node = product.get("node", {})
            product_title = product_node.get("title", "")

            for variant in (product_node.get("variants") or {}).get("edges", []) or []:
                v_node = variant.get("node", {})
                inv_item_global = (v_node.get("inventoryItem") or {}).get("id")
                inv_item_numeric = inv_item_global.split("/")[-1] if inv_item_global else None
                qty = 0
                if inv_item_numeric and inv_item_numeric in inventory_levels_map:
                    qty = inventory_levels_map[inv_item_numeric].get("loc1_qty", 0)
                if not qty:
                    continue

                rows.append({
                    "product_title": product_title,
                    "variant_title": v_node.get("title", "") or "",
                    "sku": v_node.get("sku", "") or "",
                    "quantity": qty,
                })

        rows.sort(key=lambda row: (row.get("product_title", ""), row.get("variant_title", ""), row.get("sku", "")))
        return {
            "rows": rows,
            "row_count": len(rows),
            "location_id_numeric": settings.get("location_id_numeric"),
        }

    # ---------------------------
    # Settings helpers
    # ---------------------------
    def _load_settings(self) -> Dict[str, str]:
        ICP = self.env["ir.config_parameter"].sudo()
        store_domain = ICP.get_param("odoo_shopify_restock.store_domain") or ""
        access_token = ICP.get_param("odoo_shopify_restock.access_token") or ""
        api_version = ICP.get_param("odoo_shopify_restock.api_version") or "2023-04"
        location_id_global = ICP.get_param("odoo_shopify_restock.location_id_global") or ""
        location_id_numeric = ICP.get_param("odoo_shopify_restock.location_id_numeric") or ""
        project_id = ICP.get_param("odoo_shopify_restock.project_id") or "0"
        odoo_location_id = ICP.get_param("odoo_shopify_restock.odoo_location_id") or "0"
        
        # Override with location-specific settings if available
        location = self.env.context.get("shopify_restock_location")
        if location:
            if hasattr(location, 'location_id_numeric') and location.location_id_numeric:
                location_id_numeric = location.location_id_numeric
            if hasattr(location, 'location_id_global') and location.location_id_global:
                location_id_global = location.location_id_global
        
        return {
            "store_domain": store_domain.strip(),
            "access_token": access_token.strip(),
            "api_version": api_version.strip(),
            "location_id_global": location_id_global.strip(),
            "location_id_numeric": location_id_numeric.strip(),
            "project_id": project_id.strip(),
            "odoo_location_id": odoo_location_id.strip(),
        }

    # ---------------------------
    # Core logic adapted from user's script
    # ---------------------------
    def _convert_metafield_value(self, value_type: Optional[str], value: Any) -> Any:
        if value is None:
            return None
        try:
            if value_type == "number_integer":
                return int(value)
            if value_type == "number_decimal":
                return float(value)
            if value_type == "boolean":
                return str(value).lower() == "true"
            if value_type == "json":
                return json.loads(value)
            return value
        except Exception:  # pylint: disable=broad-except
            return None

    def _get_metafield_value(self, metafields: Optional[Dict[str, Any]], target_key: str) -> Any:
        if not metafields:
            return None
        for edge in metafields.get("edges", []) or []:
            node = edge.get("node", {})
            if node.get("key") == target_key:
                return self._convert_metafield_value(node.get("type"), node.get("value"))
        return None

    def _is_published_to_online_store(self, publications: Optional[Dict[str, Any]]) -> bool:
        if not publications:
            return False
        for edge in publications.get("edges", []) or []:
            node = edge.get("node", {})
            channel = node.get("channel", {})
            channel_handle = (channel.get("handle") or "").lower()
            channel_name = (channel.get("name") or "").lower()
            is_online_store = (
                channel_handle in ["online-store", "online_store"]
                or "online store" in channel_name
                or channel_name == "online store"
            )
            if is_online_store and node.get("isPublished"):
                return True
        return False

    def _is_published_to_channel(
        self,
        publications: Optional[Dict[str, Any]],
        *,
        target_names: Optional[List[str]] = None,
        target_handles: Optional[List[str]] = None,
    ) -> bool:
        """Check whether a product is published to any of the target channels."""
        if not publications:
            return False
        name_targets = {name.strip().lower() for name in (target_names or []) if name}
        handle_targets = {handle.strip().lower() for handle in (target_handles or []) if handle}
        if not name_targets and not handle_targets:
            return False
        for edge in publications.get("edges", []) or []:
            node = edge.get("node", {})
            if not node.get("isPublished"):
                continue
            channel = node.get("channel", {})
            channel_name = (channel.get("name") or "").strip().lower()
            channel_handle = (channel.get("handle") or "").strip().lower()
            if channel_name in name_targets or channel_handle in handle_targets:
                return True
        return False

    def _fetch_all_products(self, settings: Dict[str, str]) -> List[Dict[str, Any]]:
        query = (
            "\n"
            "    query ($cursor: String) {\n"
            "      products(first: 50, after: $cursor) {\n"
            "        edges {\n"
            "          node {\n"
            "            id\n"
            "            title\n"
            "            handle\n"
            "            metafields(namespace: \"custom\", first: 5) {\n"
            "              edges { node { key value type } }\n"
            "            }\n"
            "            publications(first: 10) {\n"
            "              edges { node { channel { id name handle } isPublished publishDate } }\n"
            "            }\n"
            "            variants(first: 50) {\n"
            "              edges {\n"
            "                node {\n"
            "                  id title sku\n"
            "                  inventoryItem { id }\n"
            "                  metafields(namespace: \"custom\", first: 5) {\n"
            "                    edges { node { key value type } }\n"
            "                  }\n"
            "                }\n"
            "              }\n"
            "            }\n"
            "          }\n"
            "        }\n"
            "        pageInfo { hasNextPage endCursor }\n"
            "      }\n"
            "    }\n"
        )
        all_products: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": settings["access_token"],
        }
        base_url = f"https://{settings['store_domain']}/admin/api/{settings['api_version']}/graphql.json"
        while True:
            variables = {"cursor": cursor} if cursor else {}
            response = requests.post(base_url, headers=headers, json={"query": query, "variables": variables}, timeout=60)
            response.raise_for_status()
            response_json = response.json()
            if "data" not in response_json:
                raise ValueError(f"GraphQL query error: {response_json.get('errors')}")
            products_data = response_json["data"]["products"]
            all_products.extend(products_data["edges"]) 
            if not products_data["pageInfo"]["hasNextPage"]:
                break
            cursor = products_data["pageInfo"]["endCursor"]
        return all_products

    def _fetch_inventory_levels_for_items(self, settings: Dict[str, str], inventory_item_ids: List[str]) -> Dict[str, Dict[str, int]]:
        if not inventory_item_ids:
            return {}
        inv_map: Dict[str, Dict[str, int]] = {}
        chunk_size = 50
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": settings["access_token"],
        }
        for i in range(0, len(inventory_item_ids), chunk_size):
            chunk = inventory_item_ids[i : i + chunk_size]
            numeric_ids = [inv_id.split("/")[-1] for inv_id in chunk]
            id_list_str = ",".join(numeric_ids)
            url = (
                f"https://{settings['store_domain']}/admin/api/{settings['api_version']}/"
                f"inventory_levels.json?inventory_item_ids={id_list_str}&limit=250"
            )
            response = requests.get(url, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()
            levels = data.get("inventory_levels", []) or []
            for level in levels:
                inv_item_id = str(level.get("inventory_item_id"))
                loc_id = str(level.get("location_id"))
                available = int(level.get("available") or 0)
                if inv_item_id not in inv_map:
                    inv_map[inv_item_id] = {}
                if loc_id == settings["location_id_numeric"]:
                    inv_map[inv_item_id]["loc1_qty"] = available
        return inv_map

    def _generate_report(self, settings: Dict[str, str]) -> Dict[str, Any]:
        # Basic validation
        required = ["store_domain", "access_token", "api_version", "location_id_numeric"]
        for key in required:
            if not settings.get(key):
                raise ValueError(f"Missing configuration: {key}")

        products = self._fetch_all_products(settings)

        # Filter to only Online Store products, and optionally Retail Store
        online_store_products: List[Dict[str, Any]] = []
        location = self.env.context.get("shopify_restock_location")
        location_name = (getattr(location, "name", "") or "").strip().lower()
        require_retail_publication = bool(location_name and "retail" in location_name)
        is_fulfillment_location = bool(location_name and (
            "fulfill" in location_name or "fulfil" in location_name
        ))
        enforce_online_store = is_fulfillment_location
        if location:
            _logger.debug(
                "Running restock for location '%s' (require retail=%s, enforce online store=%s)",
                getattr(location, "name", location_name),
                require_retail_publication,
                enforce_online_store,
            )
        for product in products:
            product_node = product.get("node", {})
            publications = product_node.get("publications")
            product_title = product_node.get("title") or product_node.get("id") or "<no title>"
            published_online = self._is_published_to_online_store(publications)
            published_retail = None
            if require_retail_publication or not enforce_online_store:
                published_retail = self._is_published_to_channel(
                    publications,
                    target_names=[
                        "retail store",
                        "point of sale",
                    ],
                    target_handles=[
                        "retail-store",
                        "retail_store",
                        "retail",
                        "point-of-sale",
                        "point_of_sale",
                        "shopify-pos",
                        "shopify_pos",
                        "pos",
                    ],
                )

            if enforce_online_store and not published_online:
                _logger.debug("Skipping '%s': not published to Online Store", product_title)
                continue

            if require_retail_publication and not published_retail:
                channel_snapshots: List[str] = []
                for edge in (publications or {}).get("edges", []) or []:
                    node = edge.get("node", {})
                    channel = node.get("channel", {})
                    channel_snapshots.append(
                        f"{channel.get('name')} ({channel.get('handle')}): {node.get('isPublished')}"
                    )
                _logger.debug(
                    "Skipping '%s': not published to Retail store. Channels: %s",
                    product_title,
                    "; ".join(filter(None, channel_snapshots)) or "<none>",
                )
                continue

            if not enforce_online_store and not (published_online or published_retail):
                _logger.debug(
                    "Skipping '%s': not published to Online Store or Retail store",
                    product_title,
                )
                continue
            _logger.debug("Including '%s' for report", product_title)
            online_store_products.append(product)

        # Collect inventory item ids
        inventory_item_ids: List[str] = []
        for product in online_store_products:
            product_node = product["node"]
            for variant in product_node["variants"]["edges"]:
                v_node = variant["node"]
                inv_item = v_node.get("inventoryItem")
                if inv_item and inv_item.get("id"):
                    inventory_item_ids.append(inv_item["id"])

        inventory_levels_map = self._fetch_inventory_levels_for_items(settings, inventory_item_ids)
        report_date = datetime.now().strftime("%Y-%m-%d")
        current_timestamp_dt = fields.Datetime.now()
        current_timestamp = fields.Datetime.to_string(current_timestamp_dt)

        rss_items: List[Dict[str, Any]] = []
        alert_rows: List[List[Any]] = []

        store_short = settings["store_domain"].replace(".myshopify.com", "")

        for product in online_store_products:
            product_node = product["node"]
            product_id = product_node.get("id", "")
            product_title = product_node.get("title", "")
            product_handle = product_node.get("handle", "")

            product_restock = self._get_metafield_value(product_node.get("metafields"), "restock_level")
            product_desired = self._get_metafield_value(product_node.get("metafields"), "desired_inventory_level")

            for variant in product_node["variants"]["edges"]:
                v_node = variant["node"]
                variant_id = v_node.get("id", "")
                sku = v_node.get("sku", "")
                variant_title = v_node.get("title", "")

                variant_restock = self._get_metafield_value(v_node.get("metafields"), "restock_level")
                variant_desired = self._get_metafield_value(v_node.get("metafields"), "desired_inventory_level")

                final_restock = variant_restock or product_restock
                final_desired = variant_desired or product_desired

                inv_item_global = v_node.get("inventoryItem", {}).get("id")
                inv_item_numeric = inv_item_global.split("/")[-1] if inv_item_global else None

                loc1_qty = 0
                if inv_item_numeric and inv_item_numeric in inventory_levels_map:
                    loc1_qty = inventory_levels_map[inv_item_numeric].get("loc1_qty", 0)

                needs_restock = False
                restock_amount = 0

                if final_restock and loc1_qty < final_restock:
                    needs_restock = True
                    restock_amount = (final_desired - loc1_qty) if final_desired else 0

                    display_title = f"{product_title}"
                    if variant_title and variant_title != "Default Title":
                        display_title += f" - {variant_title}"

                    unique_id = f"restock-{product_id}-{variant_id}-{report_date}"

                    product_url = f"https://{store_short}.com/products/{product_handle}"
                    if variant_title and variant_title != "Default Title":
                        variant_numeric_id = variant_id.split("/")[-1] if variant_id else ""
                        product_url += f"?variant={variant_numeric_id}"

                    urgency = (
                        "high" if loc1_qty == 0 else "medium" if (final_restock and loc1_qty < (final_restock * 0.5)) else "low"
                    )

                    rss_item = {
                        "id": unique_id,
                        "title": f"RESTOCK ALERT: {display_title}",
                        "description": (
                            f"Product: {product_title}\nVariant: {variant_title}\nSKU: {sku}\n"
                            f"Current Stock: {loc1_qty} units\nRestock Level: {final_restock} units\n"
                            f"Recommended Order: {restock_amount} units\nGenerated: {current_timestamp}"
                        ),
                        "link": product_url,
                        "guid": unique_id,
                        "pubDate": current_timestamp,
                        "category": "inventory-alert",
                        "product_title": product_title,
                        "variant_title": variant_title,
                        "sku": sku,
                        "current_qty": loc1_qty,
                        "restock_level": final_restock,
                        "restock_amount": restock_amount,
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "product_handle": product_handle,
                        "urgency": urgency,
                    }

                    rss_items.append(rss_item)

                if needs_restock:
                    alert_rows.append([product_title, variant_title, sku, loc1_qty, restock_amount])

        if rss_items:
            # Build an HTML table for email and UI
            rows = []
            rows.append("<tr><th>Urgency</th><th>Product</th><th>Variant</th><th>SKU</th><th>Current</th><th>Restock Level</th><th>Recommend</th></tr>")
            for it in rss_items:
                rows.append(
                    "<tr>"
                    f"<td>{it.get('urgency','')}</td>"
                    f"<td>{(it.get('product_title') or '').replace('<','&lt;').replace('>','&gt;')}</td>"
                    f"<td>{(it.get('variant_title') or '').replace('<','&lt;').replace('>','&gt;')}</td>"
                    f"<td>{it.get('sku') or ''}</td>"
                    f"<td>{it.get('current_qty') or 0}</td>"
                    f"<td>{it.get('restock_level') or ''}</td>"
                    f"<td>{it.get('restock_amount') or 0}</td>"
                    "</tr>"
                )
            table_html = "<table border=1 cellspacing=0 cellpadding=4>" + "".join(rows) + "</table>"
            email_body = (
                f"<html><body>\n"
                f"<p>Inventory Report: {len(rss_items)} items need restocking.</p>\n"
                f"{table_html}"
                f"<p>Generated: {current_timestamp}</p>\n"
                f"</body></html>"
            )
        else:
            email_body = "<html><body><p>No Online Store items require restocking at this time.</p></body></html>"

        result = {
            "rss_items": rss_items,
            "rss_item_count": len(rss_items),
            "has_restock_alerts": bool(rss_items),
            # Store a true datetime for ORM create
            "report_timestamp": current_timestamp_dt,
            "report_date": report_date,
            "email_body": email_body,
            "total_products_checked": len(online_store_products),
            "total_products_found": len(products),
            "alert_rows": alert_rows,
            "todo_count": len(rss_items),
        }
        _logger.debug(
            "Restock report complete: %s products fetched, %s in scope, %s alerts",
            len(products),
            len(online_store_products),
            len(rss_items),
        )
        return result

    def _get_task_user_id(self, settings: Dict[str, str]) -> Optional[int]:
        ctx_user_id = self.env.context.get("restock_user_id")
        if ctx_user_id and str(ctx_user_id).isdigit():
            return int(ctx_user_id)
        ctx_employee_id = self.env.context.get("restock_employee_id")
        if ctx_employee_id and str(ctx_employee_id).isdigit():
            employee = self.env["hr.employee"].sudo().browse(int(ctx_employee_id))
            if employee and employee.user_id:
                return employee.user_id.id
        return None

    def _get_restock_project(self, settings: Dict[str, str]) -> models.Model:
        project_id = settings.get("project_id")
        if project_id and str(project_id).isdigit():
            project = self.env["project.project"].sudo().browse(int(project_id))
            if project and project.exists():
                self._ensure_project_has_done_stage(project)
                self._ensure_runner_project_access(project)
                return project
        project = self.env["project.project"].sudo().search([("name", "=", "Shopify Restock")], limit=1)
        if not project:
            project = self.env["project.project"].sudo().create({
                "name": "Shopify Restock",
                "company_id": self.env.company.id,
            })
        self._ensure_project_has_done_stage(project)
        self._ensure_runner_project_access(project)
        return project

    def _ensure_project_has_done_stage(self, project: models.Model) -> None:
        """Ensure the project has a 'Done' stage (folded in kanban).

        Note: In Odoo 18, task completion is determined by task.state ('1_done'),
        not by the stage. However, having a folded 'Done' stage helps organize
        the kanban view.
        """
        if not project:
            return
        stage_model = self.env["project.task.type"].sudo()

        # Check if project already has a "Done" stage by name
        done_stage = stage_model.search([
            ("project_ids", "in", project.id),
            ("name", "ilike", "done"),
        ], limit=1)

        if done_stage:
            return

        # Create a Done stage for this project
        stage_vals = {
            "name": "Done",
            "project_ids": [(4, project.id)],
            "sequence": 100,
        }
        # Set fold=True if the field exists (hides in kanban)
        if "fold" in stage_model._fields:
            stage_vals["fold"] = True

        stage_model.create(stage_vals)
        _logger.info("Created 'Done' stage for Shopify Restock project %s", project.id)

    def _ensure_runner_project_access(self, project: models.Model) -> None:
        """Ensure the user running the report can see the project (follower/member)."""
        if not project:
            return
        self._ensure_project_actions_have_fallback_views()
        run_by_uid = self.env.context.get("restock_run_by_uid")
        if not run_by_uid or not str(run_by_uid).isdigit():
            return
        run_by_user = self.env["res.users"].sudo().browse(int(run_by_uid))
        if not run_by_user or not run_by_user.exists():
            return
        # Unarchive if needed
        if "active" in project._fields and not project.active:
            project.sudo().write({"active": True})
        # Align project company with the runner's active company when possible
        if run_by_user.company_id:
            if "company_ids" in project._fields:
                project.sudo().write({"company_ids": [(4, run_by_user.company_id.id)]})
            if "company_id" in project._fields:
                if not project.company_id or project.company_id.id != run_by_user.company_id.id:
                    project.sudo().write({"company_id": run_by_user.company_id.id})
        # Prefer visibility to all internal users when supported
        if "privacy_visibility" in project._fields:
            selection = project._fields["privacy_visibility"].selection or []
            allowed = {value for value, _label in selection}
            target = None
            for candidate in ("employees", "internal", "company"):
                if candidate in allowed:
                    target = candidate
                    break
            if target and project.privacy_visibility != target:
                project.sudo().write({"privacy_visibility": target})
        # Subscribe runner as follower (covers 'followers-only' visibility)
        if run_by_user.partner_id:
            project.with_context(
                mail_notify_force_send=False,
                mail_auto_subscribe_no_notify=True,
            ).sudo().message_subscribe(partner_ids=[run_by_user.partner_id.id])
        # Also add as project member if the field exists
        if "user_ids" in project._fields:
            project.sudo().write({"user_ids": [(4, run_by_user.id)]})
        elif "member_ids" in project._fields:
            project.sudo().write({"member_ids": [(4, run_by_user.id)]})

    def _ensure_project_actions_have_fallback_views(self) -> None:
        """Prevent timeline-only actions from erroring if timeline view isn't available."""
        action_model = self.env["ir.actions.act_window"].sudo()
        view_model = self.env["ir.ui.view"].sudo()
        actions = action_model.search([
            ("view_mode", "ilike", "timeline"),
            ("res_model", "ilike", "project."),
        ])
        for action in actions:
            modes = [m.strip() for m in (action.view_mode or "").split(",") if m.strip()]
            if not modes:
                continue
            has_timeline_view = bool(view_model.search([
                ("model", "=", action.res_model),
                ("type", "=", "timeline"),
            ], limit=1))
            if not has_timeline_view:
                modes = [m for m in modes if m != "timeline"]
            else:
                if modes[0] == "timeline" and len(modes) > 1:
                    modes = [m for m in modes if m != "timeline"] + ["timeline"]
            if not modes:
                modes = ["kanban", "tree", "form"]
            # Deduplicate while preserving order
            seen = set()
            normalized = []
            for mode in modes:
                if mode in seen:
                    continue
                seen.add(mode)
                normalized.append(mode)
            action.write({"view_mode": ",".join(normalized)})

    def _create_tasks_for_items(
        self,
        settings: Dict[str, str],
        items: models.Model,
        run: models.Model,
        location: Optional[models.Model] = None,
    ) -> None:
        if not items:
            _logger.warning("No items to create tasks for")
            return
        _logger.info("Creating tasks for %d restock items", len(items))
        project = self._get_restock_project(settings)
        user_id = self._get_task_user_id(settings)
        run_by_uid = self.env.context.get("restock_run_by_uid")
        run_by_partner_id = None
        if run_by_uid and str(run_by_uid).isdigit():
            run_by_user = self.env["res.users"].sudo().browse(int(run_by_uid))
            if run_by_user and run_by_user.partner_id:
                run_by_partner_id = run_by_user.partner_id.id
        _logger.info("Using project %s (ID: %s), user_id: %s",
                     project.name if project else None,
                     project.id if project else None,
                     user_id)
        task_model = self.env["project.task"]
        tasks_created = 0
        tasks_merged = 0
        for item in items:
            try:
                existing_task = self._find_existing_task_for_item(task_model, project, item)
                if existing_task and not existing_task._restock_task_is_done():
                    item.sudo().write({"todo_task_id": existing_task.id})
                    if not existing_task.restock_item_id:
                        existing_task.sudo().write({"restock_item_id": item.id})
                    if run_by_partner_id:
                        existing_task.with_context(
                            mail_notify_force_send=False,
                            mail_auto_subscribe_no_notify=True,
                        ).sudo().message_subscribe(partner_ids=[run_by_partner_id])
                    self._update_task_description_for_items(existing_task, location=location)
                    tasks_merged += 1
                    _logger.info(
                        "Merged restock item %s into existing task %s", item.id, existing_task.id
                    )
                    continue
                restock_qty = self._compute_needed_qty(item)
                description_lines = [
                    f"Product: {item.product_title or ''}",
                    f"Variant: {item.variant_title or ''}",
                    f"SKU: {item.sku or ''}",
                    f"Current Qty: {item.current_qty or 0}",
                    f"Restock Level: {item.restock_level or ''}",
                    f"Recommended Order: {restock_qty}",
                ]
                if item.product_url:
                    description_lines.append(f"Shopify URL: {item.product_url}")
                if location:
                    description_lines.append(f"Shopify Location: {getattr(location, 'name', '')}")
                task_vals = {
                    "name": self._build_task_title(item, restock_qty),
                    "description": "\n".join(filter(None, description_lines)),
                    "project_id": project.id if project else False,
                    "restock_item_id": item.id,
                }
                if user_id:
                    if "user_id" in task_model._fields:
                        task_vals["user_id"] = user_id
                    elif "user_ids" in task_model._fields:
                        task_vals["user_ids"] = [(6, 0, [user_id])]
                    elif "assigned_ids" in task_model._fields:
                        task_vals["assigned_ids"] = [(6, 0, [user_id])]
                task = self.env["project.task"].with_context(
                    mail_create_nosubscribe=True,
                    mail_create_nolog=True,
                    mail_auto_subscribe_no_notify=True,
                    mail_notify_force_send=False,
                    tracking_disable=True,
                ).sudo().create(task_vals)
                if run_by_partner_id:
                    task.with_context(
                        mail_notify_force_send=False,
                        mail_auto_subscribe_no_notify=True,
                    ).sudo().message_subscribe(partner_ids=[run_by_partner_id])
                item.sudo().write({"todo_task_id": task.id})
                self._update_task_description_for_items(task, location=location)
                tasks_created += 1
            except Exception as e:
                _logger.exception("Failed to create task for item %s: %s", item.id, e)
        _logger.info(
            "Created %d tasks for restock run (%d merged into existing tasks)",
            tasks_created,
            tasks_merged,
        )

    def _find_existing_task_for_item(
        self,
        task_model: models.Model,
        project: models.Model,
        item: models.Model,
    ) -> Optional[models.Model]:
        if not project or not item:
            return None
        domain = [("project_id", "=", project.id)]
        if item.location_id:
            domain.append(("restock_item_id.location_id", "=", item.location_id.id))
        if item.product_id_global and item.variant_id_global:
            domain.extend([
                ("restock_item_id.product_id_global", "=", item.product_id_global),
                ("restock_item_id.variant_id_global", "=", item.variant_id_global),
            ])
        elif item.product_id_global:
            domain.append(("restock_item_id.product_id_global", "=", item.product_id_global))
        elif item.sku:
            domain.append(("restock_item_id.sku", "=", item.sku))
        else:
            domain.extend([
                ("restock_item_id.product_title", "=", item.product_title or ""),
                ("restock_item_id.variant_title", "=", item.variant_title or ""),
            ])
        candidates = task_model.sudo().search(domain, order="id desc")
        for task in candidates:
            if not task._restock_task_is_done():
                return task
        return None

    def _update_task_description_for_items(
        self,
        task: models.Model,
        *,
        location: Optional[models.Model] = None,
    ) -> None:
        if not task:
            return
        items = self.env["shopify.restock.item"].sudo().search([
            ("todo_task_id", "=", task.id),
        ])
        if not items:
            return
        # Use the most recent item as the display source
        latest_item = items.sorted(lambda rec: rec.id)[-1]
        total_restock_qty = sum(self._compute_needed_qty(it) for it in items)
        task_title = self._build_task_title(latest_item, total_restock_qty)
        description_lines = [
            f"Product: {latest_item.product_title or ''}",
            f"Variant: {latest_item.variant_title or ''}",
            f"SKU: {latest_item.sku or ''}",
            f"Current Qty: {latest_item.current_qty or 0}",
            f"Restock Level: {latest_item.restock_level or ''}",
            f"Recommended Order: {total_restock_qty}",
        ]
        if latest_item.product_url:
            description_lines.append(f"Shopify URL: {latest_item.product_url}")
        if location:
            description_lines.append(f"Shopify Location: {getattr(location, 'name', '')}")
        task.sudo().write({
            "name": task_title,
            "description": "\n".join(filter(None, description_lines)),
        })

    # ---------------------------
    # Email via Odoo's mail server
    # ---------------------------
    def _send_summary_email(self, settings: Dict[str, str], result: Dict[str, Any]) -> None:
        email_to = settings.get("email_to")
        if not email_to:
            return
        subject = (
            f"Shopify Restock: {result.get('rss_item_count', 0)} item(s) need attention"
        )
        body_html = result.get("email_body") or "<p>No details</p>"

        mail_vals = {
            "subject": subject,
            "email_to": email_to,
            "body_html": body_html,
        }
        mail = self.env["mail.mail"].sudo().create(mail_vals)
        mail.send()
