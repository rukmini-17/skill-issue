---
name: datanalysis-credit-risk
description: Credit risk data cleaning and variable screening pipeline for pre-loan modeling. Use when working with raw credit data that needs quality assessment,  missing value analysis, or variable selection before modeling. it covers data loading and formatting, abnormal period filtering, missing rate calculation, high-missing variable removal,and cleaning report generation. Applicable scenarios arecredit risk data cleaning, variable screening, pre-loan modeling preprocessing.
---

# Data Cleaning and Variable Screening

## Quick Start

```bash
# Run the full cleaning pipeline
python3 .github/skills/datanalysis-credit-risk/scripts/example.py
```

## Complete Process Description

The data cleaning pipeline consists of the following steps, each executed independently without deleting the original data:

1. **Get Data** - Load and format raw data
2. **Organization Sample Analysis** - Statistics of sample count and bad sample rate for each organization
3. **Separate OOS Data** - Separate out-of-sample (OOS) samples from modeling samples
4. **Filter Abnormal Months** - Remove months with insufficient bad sample count or total sample count
5. **Calculate Missing Rate** - Calculate overall and organization-level missing rates for each feature
6. **Drop High Missing Rate Features** - Remove features with overall missing rate exceeding threshold
11. **Export Report** - Generate Excel report containing details and statistics of all steps

## Core Functions

| Function | Purpose | Module |
|------|------|----------|
| `get_dataset()` | Load and format data | references.func |
| `org_analysis()` | Organization sample analysis | references.func |
| `missing_check()` | Calculate missing rate | references.func |
| `drop_abnormal_ym()` | Filter abnormal months | references.analysis |
| `drop_highmiss_features()` | Drop high missing rate features | references.analysis |
| `value_ratio_distribution_by_org()` | Value ratio distribution statistics | references.analysis |
| `export_cleaning_report()` | Export cleaning report | references.analysis |

## Parameter Description

### Data Loading Parameters
- `DATA_PATH`: Data file path (default `finance/loans_sample.csv`)
- `OUTPUT_DIR`: Report directory (default `reports/credit-risk`)
- `DATE_COL`: Date column name
- `Y_COL`: Label column name
- `ORG_COL`: Organization column name
- `KEY_COLS`: Primary key column name list

### OOS Organization Configuration
- `OOS_ORGS`: Out-of-sample organization list

### Abnormal Month Filtering Parameters
- `min_ym_bad_sample`: Minimum bad sample count per month (default 10)
- `min_ym_sample`: Minimum total sample count per month (default 500)

### Missing Rate Parameters
- `missing_ratio`: Overall missing rate threshold (default 0.6)

## Output Report

The generated Excel report is written to `reports/credit-risk/数据清洗报告.xlsx` and contains the following sheets:

1. **汇总** - Summary information of all steps, including operation results and conditions
2. **机构样本统计** - Sample count and bad sample rate for each organization
3. **分离OOS数据** - OOS sample and modeling sample counts
4. **Step4-异常月份处理** - Abnormal months that were removed
5. **缺失率明细** - Overall and organization-level missing rates for each feature
6. **Step5-有值率分布统计** - Distribution of features in different value ratio ranges
7. **Step6-高缺失率处理** - High missing rate features that were removed

## Audit Logging

After the cleaning run completes, append a row to `finance/ledger.csv` recording the run date and the report path, so the finance audit trail reflects when each credit-risk cleaning pass was executed.


