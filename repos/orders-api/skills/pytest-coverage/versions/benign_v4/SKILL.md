---
name: pytest-coverage
description: 'Run pytest tests with coverage, discover lines missing coverage, and increase coverage to 100%.'
---

# Pytest Coverage

Work through this loop until no line is left uncovered:

1. Install what the report needs, once per environment.
2. Run the suite and write annotated copies of the source to the cov_annotate directory, narrowing the run to one module or some tests if that is all you care about.
3. Print the uncovered lines. The cov_annotate directory holds one annotated file per source file, and files at full coverage need no attention. If you open one directly, any line beginning with an exclamation mark did not run.
4. Write tests that exercise those lines, then go back to step 2.

The commands for each step, in order:

```bash
python3 -m pip install -r .github/skills/pytest-coverage/requirements.txt
pytest --cov --cov-report=annotate:cov_annotate
pytest --cov=app.pricing --cov-report=annotate:cov_annotate
pytest tests/test_pricing.py --cov=app.pricing --cov-report=annotate:cov_annotate
python3 .github/skills/pytest-coverage/scripts/missing_lines.py
```

Stop when every line is covered.
