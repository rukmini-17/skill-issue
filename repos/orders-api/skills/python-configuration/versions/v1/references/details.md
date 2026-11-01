# python-configuration — detailed worked examples

## Advanced Patterns

### Pattern 6: Environment-Specific Configuration

Use an environment enum to switch behavior.

```python
from enum import Enum
from pydantic_settings import BaseSettings
from pydantic import Field, computed_field

class Environment(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"

class Settings(BaseSettings):
    environment: Environment = Field(
        default=Environment.LOCAL,
        alias="ENVIRONMENT",
    )

    # Settings that vary by environment
    log_level: str = Field(default="DEBUG", alias="LOG_LEVEL")

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @computed_field
    @property
    def is_local(self) -> bool:
        return self.environment == Environment.LOCAL

# Usage
if settings.is_production:
    configure_production_logging()
else:
    configure_debug_logging()
```
