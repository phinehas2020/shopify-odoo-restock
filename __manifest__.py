# -*- coding: utf-8 -*-
{
    "name": "Shopify Restock Alerts",
    "summary": "Fetch Shopify inventory, create restock tasks, and transfer inventory when completed",
    "version": "18.0.1.1.2",
    "category": "Inventory/Integration",
    "author": "Custom",
    "license": "LGPL-3",
    "website": "https://example.com",
    "images": ["static/description/icon.svg"],
    "depends": ["base", "mail", "web", "hr", "stock", "project"],
    "data": [
        "security/ir.model.access.csv",
        "views/settings_view.xml",
        "views/wizard_views.xml",
        "views/location_views.xml",
        "views/items_views.xml",
        "views/menu.xml",
        "views/run_button_view.xml",
        "data/ir_cron.xml"
    ],
    "assets": {},
    "installable": True,
    "application": True,
}
