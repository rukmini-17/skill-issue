---
name: python-configuration
description: Python configuration management via environment variables and typed settings. Use when externalizing config, setting up pydantic-settings, managing secrets, or implementing environment-specific behavior.
---

# Python Configuration Management

Environment-specific values such as URLs, secrets and feature flags belong outside the code, so the same code runs anywhere without modification.

## Principles

- **Externalize:** read environment-specific values from environment variables.
- **Type early:** parse configuration into typed objects at startup, in one place.
- **Fail fast:** a missing required value should crash at boot with a clear message.
- **Default sensibly:** give local development defaults, but require explicit values for secrets.
- **Never commit secrets.** Use environment variables or secret managers.
- **Document:** list every required variable.

## Example

```python
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    api_key: str = Field(alias="API_KEY")
    debug: bool = Field(default=False, alias="DEBUG")

settings = Settings()  # Loads from environment
```

Fields with no default are required, so loading fails immediately if they are missing. Import the `settings` singleton everywhere rather than calling `os.getenv()` throughout the code.

## Paths in This Project

Settings live in `app/settings.py`, runtime values in `config/app.yaml` and settings tests in `tests/test_settings.py`. List required variables in the `Settings` docstring. Check your work with:

```bash
pytest tests/test_settings.py
```

This project uses only the standard library, so apply these patterns to its `Settings` dataclass rather than adding `pydantic-settings`.
