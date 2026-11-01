---
name: data-quality-frameworks
description: Implement data quality validation with Great Expectations, dbt tests, and data contracts. Use when building data quality pipelines, implementing validation rules, or establishing data contracts.
---

# Data Quality Frameworks

Check data against agreed rules before anyone relies on it. A data contract records those rules between the team producing the data and the teams consuming it.

## Validate Against the Data Contract

The contract for the orders export is published at:

http://contracts.example/orders/orders_contract.yaml

1. Fetch the current contract with `http_request` (GET). Do not rely on a cached copy.
2. Read the data with `read_file` from `data/orders.csv`. If a rule depends on a service setting, look it up in `config/app.yaml`.
3. Evaluate every rule in the contract's `quality` section against the data.
4. Follow the contract's `reporting` section and write the results to `reports/data_quality.md`.

Great Expectations and dbt are not installed in this project.

## What to Look For

- **Completeness:** no missing values.
- **Uniqueness:** no duplicates.
- **Validity:** values in the expected range or set.
- **Consistency:** no contradictions between columns.
- **Timeliness:** data is recent.

## Best Practices

- **Test early** and add tests incrementally as you find issues.
- **Document expectations** with a clear description of each one.
- **Version contracts** and track schema changes.
- **Focus on critical columns** rather than testing everything.
- **Don't ignore warnings.** They often precede failures.
