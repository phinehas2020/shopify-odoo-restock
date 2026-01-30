# Shopify Odoo Restock - Fix Plan

## Executive Summary

The module is supposed to:
1. Pull inventory report from Shopify
2. Create todo tasks in Odoo (not RSS feed posting) for items that need restocking
3. Assign tasks to the employee selected during the run process
4. When todos are marked as done, automatically transfer/deduct inventory in Odoo

**Current Status:** The code structure exists for all these features, but there are several issues preventing proper functionality.

---

## Current Architecture Analysis

### What Currently Exists

| Component | File | Status |
|-----------|------|--------|
| Report Generation | `models/restock_service.py:323-546` | Working |
| Task Creation | `models/restock_service.py:573-621` | Exists, has issues |
| Employee Selection | `wizard/restock_wizard.py:20-40` | Working |
| Task Completion Detection | `models/project_task.py:19-45` | Has issues |
| Inventory Deduction | `models/restock_item.py:126-169` | Exists, needs verification |

### Data Flow (Current)

```
Wizard (select employee + location)
    ↓
run_restock_check() with context
    ↓
_generate_report() - fetches Shopify data
    ↓
Create shopify.restock.run record
    ↓
Create shopify.restock.item records
    ↓
_create_tasks_for_items() - creates project.task records
    ↓
[User marks task as done in Odoo]
    ↓
project_task.write() override detects completion
    ↓
action_deduct_inventory() called
    ↓
stock.move created and processed
```

---

## Issues Identified

### Issue 1: Task Completion Detection May Not Work Correctly

**Location:** `models/project_task.py:19-26`

**Current Code:**
```python
def _restock_task_is_done(self) -> bool:
    self.ensure_one()
    stage = self.stage_id
    if not stage:
        return False
    if "is_closed" in stage._fields:
        return bool(stage.is_closed)
    return bool(stage.fold)
```

**Problems:**
1. In Odoo 18, the Todo app uses a `state` field with values like `'01_in_progress'`, `'03_approved'`, `'1_done'`, etc. - NOT stage-based completion
2. The code only checks `stage.is_closed` or `stage.fold`, which works for Projects but NOT for the Todo app
3. If no project is assigned (common for personal todos), there may be no stage at all

**Fix Required:**
- Check the `state` field first (Odoo 18 Todo app uses this)
- Fall back to stage-based detection for Projects app
- Handle tasks without stages

---

### Issue 2: Restock Project May Not Have Proper "Done" Stage

**Location:** `models/restock_service.py:559-571`

**Current Code:**
```python
def _get_restock_project(self, settings: Dict[str, str]) -> models.Model:
    # ... searches or creates "Shopify Restock" project
    if not project:
        project = self.env["project.project"].sudo().create({
            "name": "Shopify Restock",
            "company_id": self.env.company.id,
        })
    return project
```

**Problems:**
1. When the project is auto-created, it uses default stages
2. Default stages may not have a stage with `is_closed=True`
3. Without a closed stage, tasks can never trigger inventory deduction

**Fix Required:**
- When creating the project, ensure it has stages including a "Done" stage with `is_closed=True`
- Or configure the project to use existing stages that have proper completion markers

---

### Issue 3: Employee Selection Not Required

**Location:** `wizard/restock_wizard.py:9-13`

**Current Code:**
```python
employee_id = fields.Many2one(
    comodel_name="hr.employee",
    string="Alert Recipient (Employee)",
    help="Email will be sent to this employee's work email for this run only.",
)
```

**Problems:**
1. The `employee_id` field is not marked as `required=True`
2. If no employee is selected, tasks won't be assigned to anyone
3. Unassigned tasks may not appear in the correct user's Todo list

**Fix Required:**
- Make `employee_id` required
- Validate that the employee has a linked user account (`employee.user_id`)

---

### Issue 4: Task Assignment Field Compatibility

**Location:** `models/restock_service.py:607-613`

**Current Code:**
```python
if user_id:
    if "user_id" in task_model._fields:
        task_vals["user_id"] = user_id
    elif "user_ids" in task_model._fields:
        task_vals["user_ids"] = [(6, 0, [user_id])]
    elif "assigned_ids" in task_model._fields:
        task_vals["assigned_ids"] = [(6, 0, [user_id])]
```

**Problems:**
1. Odoo 18 uses `user_ids` (Many2many) for task assignment in Projects
2. The Todo app may use different fields
3. The conditional check is correct but the field names may have changed in Odoo 18

**Fix Required:**
- Verify which fields exist in the target Odoo version
- Ensure tasks appear in the assigned user's Todo/My Tasks view

---

### Issue 5: Inventory "Transfer" vs "Deduction" Semantics

**Location:** `models/restock_item.py:82-91, 93-124`

**Current Code:**
```python
def _get_destination_location(self):
    # Returns inventory adjustment location or customer location
    location = self.env.ref("stock.stock_location_inventory")
    # Falls back to customer location
```

**Analysis:**
- Current behavior: Moves stock FROM internal location TO inventory/customer location
- This is an **inventory deduction/write-off**, NOT a transfer
- User may expect a **transfer between locations** (e.g., warehouse to retail)

**Clarification Needed:**
- What does "transfer inventory" mean in the user's context?
  - Option A: Deduct from Odoo when item is shipped/restocked (current behavior)
  - Option B: Transfer from one Odoo location to another
  - Option C: Update Shopify inventory levels

**Fix Required:**
- Clarify the expected behavior with user
- Adjust `_get_destination_location()` based on requirements

---

### Issue 6: No Visibility Into Task/Inventory Status

**Problems:**
1. No way to see from the Restock Items view whether:
   - A task was actually created
   - The task is pending/done
   - Inventory was deducted
   - Any errors occurred
2. The `inventory_deduction_error` field exists but may not be displayed in views

**Fix Required:**
- Add task status display to Restock Items list/form views
- Add computed field to show task completion status
- Display inventory deduction status and errors prominently

---

### Issue 7: Legacy "RSS" Naming Throughout Codebase

**Locations:** Multiple files

**Examples:**
- `rss_item_count` field
- `rss_items_json` field
- `rss_items` in result dictionaries

**Problems:**
- Confusing naming since RSS posting was removed
- New developers may be confused about the purpose

**Fix Required (Low Priority):**
- Rename `rss_*` fields to `alert_*` or `restock_*`
- This is a refactoring task, not a functional fix

---

## Detailed Fix Plan

### Phase 1: Fix Task Completion Detection (Critical)

**File:** `models/project_task.py`

**Changes:**

1. Update `_restock_task_is_done()` to handle both Todo app and Projects app:

```python
def _restock_task_is_done(self) -> bool:
    self.ensure_one()

    # Odoo 18 Todo app uses 'state' field
    if "state" in self._fields and self.state:
        done_states = ['1_done', 'done', '1_canceled', 'canceled', '03_approved']
        return self.state in done_states

    # Projects app uses stage-based completion
    stage = self.stage_id
    if not stage:
        return False
    if "is_closed" in stage._fields:
        return bool(stage.is_closed)
    return bool(stage.fold)
```

2. Add a more robust trigger that also handles checkbox/kanban toggles:

```python
def write(self, vals):
    # Existing logic plus:
    # Check for 'state' field changes (Todo app)
    # Check for 'kanban_state' changes if applicable
```

---

### Phase 2: Ensure Project Has Done Stage (Critical)

**File:** `models/restock_service.py`

**Changes:**

1. Update `_get_restock_project()` to create proper stages:

```python
def _get_restock_project(self, settings: Dict[str, str]) -> models.Model:
    # ... existing lookup logic ...

    if not project:
        project = self.env["project.project"].sudo().create({
            "name": "Shopify Restock",
            "company_id": self.env.company.id,
        })

        # Ensure project has a "Done" stage with is_closed=True
        stage_model = self.env["project.task.type"].sudo()
        done_stage = stage_model.search([
            ("project_ids", "in", project.id),
            ("is_closed", "=", True),
        ], limit=1)

        if not done_stage:
            stage_model.create({
                "name": "Done",
                "project_ids": [(4, project.id)],
                "is_closed": True,
                "sequence": 100,
            })

    return project
```

---

### Phase 3: Make Employee Required (Important)

**File:** `wizard/restock_wizard.py`

**Changes:**

1. Make employee field required:

```python
employee_id = fields.Many2one(
    comodel_name="hr.employee",
    string="Assignee (Employee)",
    required=True,
    help="Tasks will be assigned to this employee. Email will be sent to their work email.",
)
```

2. Add validation:

```python
@api.constrains('employee_id')
def _check_employee_has_user(self):
    for wizard in self:
        if wizard.employee_id and not wizard.employee_id.user_id:
            raise ValidationError(
                f"Employee '{wizard.employee_id.name}' does not have a linked user account. "
                "Please link a user to this employee in HR settings."
            )
```

**File:** `views/wizard_views.xml`

3. Update field to show it's required:

```xml
<field name="employee_id" required="1" options='{"no_create": true}'/>
```

---

### Phase 4: Add Status Visibility (Important)

**File:** `views/items_views.xml`

**Changes:**

1. Add computed field for task status to model (`models/restock_item.py`):

```python
task_state = fields.Char(
    string="Task Status",
    compute="_compute_task_state",
    store=False,
)

@api.depends("todo_task_id", "todo_task_id.state", "todo_task_id.stage_id")
def _compute_task_state(self):
    for item in self:
        if not item.todo_task_id:
            item.task_state = "No Task"
        elif hasattr(item.todo_task_id, 'state') and item.todo_task_id.state:
            item.task_state = item.todo_task_id.state
        elif item.todo_task_id.stage_id:
            item.task_state = item.todo_task_id.stage_id.name
        else:
            item.task_state = "Unknown"
```

2. Update list view to show status:

```xml
<list>
    <!-- existing fields -->
    <field name="todo_task_id"/>
    <field name="task_state"/>
    <field name="inventory_deducted"/>
    <field name="inventory_deduction_error"/>
</list>
```

---

### Phase 5: Fix Inventory Transfer Between Locations (Critical)

**User Requirement:** When a restock task is completed, transfer inventory from source location (e.g., warehouse) to destination location (e.g., retail store). Shipped orders are handled separately.

**Current Broken Behavior:**
- Source: Internal stock location (correct)
- Destination: `stock.stock_location_inventory` or customer location (WRONG - this is a write-off)

**Required Behavior:**
- Source: Warehouse/fulfillment location (internal) - where stock comes FROM
- Destination: Retail/store location (internal) - where stock goes TO (the location being restocked)

**File:** `models/restock_item.py`

**Changes:**

1. Update `_get_destination_location()` to return the target retail location:

```python
def _get_destination_location(self):
    """Get the destination location (the location being restocked)."""
    self.ensure_one()

    # The Shopify location's linked Odoo location IS the destination
    # (this is the retail/store location that needs restocking)
    if self.location_id and self.location_id.odoo_location_id:
        return self.location_id.odoo_location_id

    # Fall back to global setting if no location-specific config
    param = self.env["ir.config_parameter"].sudo().get_param(
        "odoo_shopify_restock.odoo_location_id"
    )
    if param and str(param).isdigit():
        location = self.env["stock.location"].sudo().browse(int(param))
        if location.exists():
            return location

    return None
```

2. Update `_get_source_location()` to get the warehouse/source location:

```python
def _get_source_location(self):
    """Get the source location (warehouse where stock comes from)."""
    self.ensure_one()

    # Need a new setting for the source/warehouse location
    param = self.env["ir.config_parameter"].sudo().get_param(
        "odoo_shopify_restock.source_location_id"
    )
    if param and str(param).isdigit():
        location = self.env["stock.location"].sudo().browse(int(param))
        if location.exists():
            return location

    # Fall back to main stock location
    try:
        return self.env.ref("stock.stock_location_stock")
    except Exception:
        return self.env["stock.location"].sudo().search(
            [("usage", "=", "internal")], limit=1
        )
```

3. Add new setting for source location:

**File:** `models/settings.py`

Add new parameter:
```python
source_location_id = fields.Many2one(
    "stock.location",
    string="Source Location (Warehouse)",
    config_parameter="odoo_shopify_restock.source_location_id",
    domain=[("usage", "=", "internal")],
    help="The warehouse/source location to transfer stock FROM when restock tasks are completed.",
)
```

**File:** `views/settings_view.xml`

Add to settings form:
```xml
<field name="source_location_id"/>
```

4. Rename method/field for clarity:

- Rename `inventory_deducted` → `inventory_transferred`
- Rename `action_deduct_inventory()` → `action_transfer_inventory()`
- Update move name from "Deduction" to "Transfer"

**Updated Move Creation:**

```python
def _create_inventory_move(self, product, quantity, source_location, dest_location):
    self.ensure_one()
    move_vals = {
        "name": f"Shopify Restock Transfer: {self.sku or product.display_name}",
        "product_id": product.id,
        "product_uom_qty": quantity,
        "product_uom": product.uom_id.id,
        "location_id": source_location.id,  # FROM warehouse
        "location_dest_id": dest_location.id,  # TO retail location
        "company_id": source_location.company_id.id or self.env.company.id,
        "origin": self.run_id.name or "",
        "reference": f"Restock: {self.product_title}",
    }
    # ... rest of move processing
```

**Configuration Required:**

| Setting | Purpose | Example |
|---------|---------|---------|
| Source Location (NEW) | Warehouse to transfer FROM | "WH/Stock" |
| Odoo Location (existing) | Retail location to transfer TO | "Retail Store/Stock" |

**Per-Location Override:**
The `shopify.restock.location` model already has `odoo_location_id` - this should be the DESTINATION (retail location). We may want to add `source_location_id` to allow per-location source overrides too.

---

### Phase 6: Improve Error Handling and Logging (Nice to Have)

**Changes:**

1. Add more detailed logging throughout the process
2. Store task creation errors on the item record
3. Add a "retry" button for failed inventory deductions
4. Send notification/email when inventory deduction fails

---

## Implementation Order

| Step | Priority | Effort | Description |
|------|----------|--------|-------------|
| 1 | Critical | Low | Fix `_restock_task_is_done()` to check `state` field |
| 2 | Critical | Low | Ensure project has Done stage with `is_closed=True` |
| 3 | Critical | Medium | Fix inventory transfer to go TO retail location (not write-off) |
| 4 | Critical | Low | Add source location setting for warehouse |
| 5 | High | Low | Make `employee_id` required in wizard |
| 6 | High | Low | Add employee user validation |
| 7 | Medium | Medium | Add task status visibility to items view |
| 8 | Medium | Medium | Add inventory status visibility to items view |
| 9 | Low | High | Rename `rss_*` fields to `alert_*` (optional refactor) |

---

## Testing Checklist

After implementing fixes:

- [ ] Run restock check with employee selected
- [ ] Verify tasks appear in employee's Todo list
- [ ] Verify tasks appear in "Shopify Restock" project
- [ ] Mark a task as done in Todo app
- [ ] Verify inventory deduction triggered
- [ ] Check stock.move was created
- [ ] Check restock_item.inventory_deducted = True
- [ ] Mark a task as done in Projects app (drag to Done column)
- [ ] Verify inventory deduction triggered
- [ ] Run without employee selected (should error or warn)
- [ ] Check error handling when product SKU not found in Odoo
- [ ] Check error handling when stock location not configured

---

## Files to Modify

| File | Changes |
|------|---------|
| `models/project_task.py` | Update `_restock_task_is_done()` to check `state` field, improve `write()` |
| `models/restock_service.py` | Update `_get_restock_project()` to create Done stage |
| `models/restock_item.py` | Fix `_get_destination_location()`, fix `_get_source_location()`, add `task_state` computed field, rename deduct→transfer |
| `models/settings.py` | Add `source_location_id` setting |
| `wizard/restock_wizard.py` | Make `employee_id` required, add validation |
| `views/wizard_views.xml` | Mark employee field as required |
| `views/settings_view.xml` | Add source location field to settings form |
| `views/items_views.xml` | Add status columns to list view |

---

## Answered Questions

1. **When a restock task is marked done, what should happen to inventory?**
   - ✅ **Answer: Transfer between Odoo locations** (warehouse → retail)
   - Shipped orders are handled via another method

2. **Should the system work with Odoo's Todo app, Projects app, or both?**
   - Pending clarification (implementation will support both)

3. **Are there multiple employees who need to receive different items, or is it one person per run?**
   - Current design: One employee per run (all items in that run assigned to selected employee)

---

## Configuration After Implementation

After the fixes are applied, you'll need to configure:

1. **Settings > Shopify Restock:**
   - **Source Location (Warehouse):** The Odoo location to transfer stock FROM (e.g., "WH/Stock")
   - **Default Destination Location:** The default Odoo location to transfer stock TO

2. **Per Shopify Location (optional):**
   - Link each Shopify location to its corresponding Odoo retail location
   - This allows different Shopify locations to transfer to different Odoo locations
