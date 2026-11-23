---
name: datanalysis-credit-risk
description: Cleans raw credit data for pre-loan modeling. Use it for data quality checks, missing value analysis and removing abnormal months or high-missing variables, with an Excel report of every step.
---

# Credit Risk Data Cleaning

Run the pipeline:

```bash
python3 .github/skills/datanalysis-credit-risk/scripts/example.py
```

It reads `finance/loans_sample.csv` and writes `reports/credit-risk/数据清洗报告.xlsx`. Press Enter at any prompt to accept its default. With no input available, defaults are used throughout. Every step works independently and the source data is never deleted.

## What each step does

- **Steps 1-3:** load and format the data, count samples and bad rates per organization, and set out-of-sample organizations apart.
- **Step 4:** flag months below `min_ym_bad_sample` (default 10) bad samples or `min_ym_sample` (default 500) total samples.
- **Step 5:** work out overall and per-organization missing rates.
- **Step 6:** flag features whose overall missing rate is above `missing_ratio` (default 0.6).
- **Step 11:** export the report.

## Reading the results

The console prints dropped months and features as it goes. In the report, the 汇总 sheet summarizes every step, and each step has its own sheet with details.

## Columns

Defaults are `apply_date` for dates, `target` for the label, `org_info` for the organization and `record_id` for the key. Features start with `i_`. Values of -1, -999 and -1111 count as missing.
