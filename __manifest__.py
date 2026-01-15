# -*- coding: utf-8 -*-
{
    "name": "Shopify Restock Alerts",
    "summary": "Fetch Shopify inventory and email restock alerts using Odoo mail server",
    "version": "18.0.1.0.5",
    "category": "Inventory/Integration",
    "author": "Custom",
    "license": "LGPL-3",
    "website": "https://example.com",
    "images": ["static/description/icon.svg"],
    "depends": ["base", "mail", "web", "hr", "stock"],
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
