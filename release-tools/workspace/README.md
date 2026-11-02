# relkit

Small helpers for cutting releases: semantic version parsing, version bumps, and
Keep a Changelog section rendering.

## Install

```bash
pip install -r requirements.txt
```

## Use

```python
from relkit import parse, bump, render_section

parse("0.3.0")          # (0, 3, 0)
bump("0.3.0", "minor")  # "0.4.0"
```

## Release

Run `./release.sh --check` before cutting a release. See `docs/release-process.md`.

## Layout

| Path | Purpose |
| --- | --- |
| `src/relkit/` | Library source |
| `tests/` | Test suite |
| `docs/` | Project documentation |
| `config/release.yaml` | Release configuration |
