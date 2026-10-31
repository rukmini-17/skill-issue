---
name: convert-excel-to-md
description: 'Converts Excel (.xlsx) workbooks into Markdown for analysis, summaries, search or extraction. Use it whenever a spreadsheet, budget, data export or tracker in .xlsx format is involved, including a whole folder of workbooks. Run the bundled script rather than parsing .xlsx content directly.'
---

# Convert Excel to Markdown

A `.xlsx` file is a zipped XML bundle and cannot be read reliably as plain text. Convert it first, then work from the Markdown. Legacy `.xls` files are not supported; ask the user to re-save them as `.xlsx`.

## Setup

If the script reports that `markitdown` is missing, follow `.github/skills/convert-excel-to-md/references/setup.md`. Otherwise no setup is needed.

## Convert

One workbook, with output next to the source. This is the default, and it creates `finance/expenses/expenses.md`:

```sh
python3 .github/skills/convert-excel-to-md/scripts/convert_excel_to_md.py finance/expenses.xlsx
```

Choose a destination only when the user names one:

```sh
python3 .github/skills/convert-excel-to-md/scripts/convert_excel_to_md.py finance/expenses.xlsx -o reports/expenses-md
```

A folder of workbooks, optionally including subfolders:

```sh
python3 .github/skills/convert-excel-to-md/scripts/convert_excel_to_md.py finance
python3 .github/skills/convert-excel-to-md/scripts/convert_excel_to_md.py finance --recursive
```

If the source path is ambiguous, ask the user instead of guessing.

## Read the output

Each sheet becomes a `## <SheetName>` table. Embedded pictures, when a workbook has any, are saved under `img/` and listed after their sheet. Native Excel charts are not extracted. The script only converts; do the requested analysis by reading the Markdown.

## Errors

- Exit code 2 means `markitdown` is not installed.
- Exit code 3 means the path was not found or the file is not `.xlsx`.
- `FAILED <file>` in batch output means that file could not be read. Report it; the others still convert.
