#!/bin/sh
set -eu
python3 .github/skills/convert-excel-to-md/scripts/convert_excel_to_md.py finance/expenses.xlsx -o reports/expenses-md
set -eu
cp -R "$REF/files/." .
