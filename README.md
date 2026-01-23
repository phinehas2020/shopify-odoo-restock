# Shopify Restock Alerts (Odoo Addon)

This module pulls Shopify inventory data, sends restock alerts, and can generate a retail inventory CSV on demand.

## Setup
- Go to Shopify Restock > Settings.
- Enter Shopify Store Domain, Access Token, and API Version.
- Set the Shopify Location IDs (global and numeric) or create locations under Shopify Restock > Locations.
- Restock alerts create Odoo to-do tasks for each item.

## Run Restock Check
- Go to Shopify Restock > Run Now.
- Pick the recipient and (optionally) a location, then click Run now.
- Results are saved under Shopify Restock > Runs and Restock Items.

## Retail Inventory Report (CSV)
- Go to Shopify Restock > Retail Inventory.
- Pick the retail location (recommended) and click Generate CSV.
- The report includes only items with stock on hand at that location.
