"""Load a source-config YAML file into a validated SourceConfig.

Supports ``${ENV_VAR}`` substitution anywhere in the YAML text so secrets
(e.g. a GitHub token used by ``bearer_token`` auth) never need to be committed
to a config file — they live in the environment (see .env.example) and are
interpolated at load time.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.schema import SourceConfig

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigValidationError(Exception):
    """Raised when a source config file fails schema validation."""


def _substitute_env_vars(raw_text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise ConfigValidationError(
                f"config references ${{{var_name}}} but that environment variable is not set"
            )
        return value

    return _ENV_VAR_PATTERN.sub(_replace, raw_text)


def load_source_config(path: str | Path) -> SourceConfig:
    """Read, env-substitute, parse, and validate a single source config file."""
    path = Path(path)
    raw_text = path.read_text(encoding="utf-8")
    substituted = _substitute_env_vars(raw_text)
    data = yaml.safe_load(substituted)
    try:
        return SourceConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigValidationError(f"{path}: {exc}") from exc


def load_all_source_configs(directory: str | Path) -> dict[str, SourceConfig]:
    """Load every *.yaml/*.yml file in a directory, keyed by source_id."""
    directory = Path(directory)
    configs: dict[str, SourceConfig] = {}
    for file_path in sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml")):
        config = load_source_config(file_path)
        if config.source_id in configs:
            raise ConfigValidationError(
                f"duplicate source_id {config.source_id!r} in {file_path} and elsewhere"
            )
        configs[config.source_id] = config
    return configs
