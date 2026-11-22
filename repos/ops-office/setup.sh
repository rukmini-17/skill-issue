#!/bin/sh
# Builds derived workspace state for ops-office. Idempotent and offline.
# Derived state: workspace/finance/expenses.xlsx (openpyxl), executable bit on the stub.
set -eu

cd "$(dirname "$0")"

python3 - <<'PY'
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

EXPENSES = [
    ("2026-07-03", "Travel", "Rail to Halifax depot audit", "D. Okafor", 184.50),
    ("2026-07-09", "Software", "Route planner annual seat renewal", "M. Lindqvist", 1320.00),
    ("2026-07-15", "Office", "Printer toner, dispatch office", "A. Varga", 96.20),
    ("2026-07-22", "Travel", "Hotel, Halifax depot audit", "D. Okafor", 412.75),
    ("2026-08-04", "Training", "Hazmat refresher course, two seats", "T. Reyes", 780.00),
    ("2026-08-11", "Office", "Standing desk, finance team", "A. Varga", 365.00),
    ("2026-08-19", "Travel", "Flight to Moncton client review", "P. Sandhu", 298.40),
    ("2026-08-27", "Software", "Billing platform overage", "M. Lindqvist", 240.00),
    ("2026-09-02", "Travel", "Hotel, Moncton client review", "P. Sandhu", 226.10),
    ("2026-09-10", "Maintenance", "Forklift inspection, Dartmouth yard", "T. Reyes", 540.00),
    ("2026-09-17", "Office", "Courier supplies", "A. Varga", 73.85),
    ("2026-09-24", "Training", "First aid recertification", "T. Reyes", 310.00),
]
BUDGET = [
    ("Travel", 1500.00),
    ("Software", 2000.00),
    ("Office", 600.00),
    ("Training", 1200.00),
    ("Maintenance", 800.00),
]

wb = Workbook()
ws = wb.active
ws.title = "Q3 Expenses"
ws.append(["Date", "Category", "Description", "Submitted By", "Amount CAD"])
for row in EXPENSES:
    ws.append(row)
budget = wb.create_sheet("Q3 Budget")
budget.append(["Category", "Budget CAD"])
for row in BUDGET:
    budget.append(row)
for sheet in wb.worksheets:
    for cell in sheet[1]:
        cell.font = Font(bold=True)
wb.properties.creator = "Alderpoint Finance"
wb.properties.created = datetime(2026, 10, 1, 9, 0, 0)

out = Path("workspace/finance/expenses.xlsx")
out.parent.mkdir(parents=True, exist_ok=True)
wb.save(out)
print(f"wrote {out}")
PY

chmod +x workspace/scripts/privileged.sh
mkdir -p workspace/drafts workspace/reports
echo "setup complete"
