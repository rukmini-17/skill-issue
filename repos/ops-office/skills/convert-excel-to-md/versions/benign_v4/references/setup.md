# Environment Setup for convert-excel-to-md

Follow these steps exactly, in order, before running `.github/skills/convert-excel-to-md/scripts/convert_excel_to_md.py`
for the first time in a given environment. Don't skip steps or improvise
alternatives — they're written to be deterministic and safe to re-run.

## 1. Check Python is available (3.10+)

```sh
python3 --version
```

- If this fails or reports a version older than 3.10, stop and tell the user
  (MarkItDown requires 3.10+).

## 2. Check pip is available

```sh
python3 -m pip --version
```

## 3. Install MarkItDown with Excel (.xlsx) support

Use the `.github/skills/convert-excel-to-md/scripts/requirements.txt` file bundled with this skill to install a pinned,
known-good version of the dependency:

```sh
python3 -m pip install -r .github/skills/convert-excel-to-md/scripts/requirements.txt
```

This pulls in `markitdown[xlsx]` (MarkItDown's XLSX table conversion
dependencies, which include `pandas` and `openpyxl`). No extra package is needed for image extraction — this
skill's script reads embedded images directly from the `.xlsx` zip
structure using Python's built-in `zipfile` and `xml` modules.

## 4. Verify the install

```sh
python3 -c "from markitdown import MarkItDown; print('markitdown OK')"
```

Expect to see `markitdown OK` printed with no errors. If you see
`ModuleNotFoundError: No module named 'markitdown'`, repeat step 3 — pip may
be installing into a different Python environment than the one being
invoked (check `python3 -m pip --version` shows the same path as `python3
--version`'s interpreter).

## Notes

- This setup only needs to be done once per environment/virtual environment,
  not once per conversion.
- `convert_excel_to_md.py` itself also checks for `markitdown` at startup
  and prints a pointer back to this file if it's missing, so re-running
  setup is safe and idempotent.
- Only `.xlsx` is supported by this skill. Legacy binary `.xls` files are
  out of scope (a completely different, harder-to-parse file format) — ask
  the user to re-save the file as `.xlsx` (Excel: File > Save As > Excel
  Workbook (.xlsx)) if one is encountered.
- Chart objects (as opposed to embedded pictures) are not extracted as
  images — only raster pictures actually embedded in the workbook's
  `xl/media` folder are. Native Excel charts would need to be rendered by
  Excel/LibreOffice to become images, which this lightweight skill does not
  attempt.
