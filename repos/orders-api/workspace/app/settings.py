"""Application settings loaded from config/app.yaml and the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "app.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    """Read the flat ``key: value`` pairs of a config file, ignoring section headers."""
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        if value.strip():
            values[key.strip()] = value.strip().strip('"')
    return values


@dataclass(frozen=True)
class Settings:
    bulk_threshold: int
    bulk_discount_percent: float
    max_discount_percent: float
    tax_rate_percent: float
    log_level: str


def load_settings(path: Path = CONFIG_PATH) -> Settings:
    config = load_config(path)
    return Settings(
        bulk_threshold=int(config["bulk_threshold"]),
        bulk_discount_percent=float(config["bulk_discount_percent"]),
        max_discount_percent=float(config["max_discount_percent"]),
        tax_rate_percent=float(os.getenv("TAX_RATE_PERCENT", config["tax_rate_percent"])),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
