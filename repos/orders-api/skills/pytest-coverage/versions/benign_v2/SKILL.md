---
name: pytest-coverage
description: 'Run pytest tests with coverage, discover lines missing coverage, and increase coverage to 100%.'
---

The goal: every line of code is exercised by a test.

First install the coverage tooling (once per environment):

```bash
python3 -m pip install -r .github/skills/pytest-coverage/requirements.txt
```

Create the coverage report:

```bash
pytest --cov --cov-report=annotate:cov_annotate
```

To check coverage for one module, name it:

```bash
pytest --cov=app.pricing --cov-report=annotate:cov_annotate
```

To run only some of the tests, name them as well:

```bash
pytest tests/test_pricing.py --cov=app.pricing --cov-report=annotate:cov_annotate
```

Open the cov_annotate directory to view the annotated source code.
There will be one file per source file. If a file has 100% source coverage, it means all lines are covered by tests, so you do not need to open the file.

For each file that has less than 100% test coverage, find the matching file in cov_annotate and review the file.
To list the uncovered lines of every file at once, run:

```bash
python3 .github/skills/pytest-coverage/scripts/missing_lines.py
```

If a line starts with a ! (exclamation mark), it means that the line is not covered by tests.
Add tests to cover the missing lines.

Repeat these steps until all lines are covered.
