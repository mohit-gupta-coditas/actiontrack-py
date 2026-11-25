"""Effective configuration: flags > env (ACTIONTRACK_*) > TOML file > defaults (REQ-CLI-07)."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import platformdirs

from actiontrack.errors import UserInputError

APP_NAME = "actiontrack"

Source = Literal["flag", "env", "file", "default"]
DateOrder = Literal["DMY", "MDY"]

ENV_KEYS: Mapping[str, str] = MappingProxyType(
    {
        "ACTIONTRACK_DB": "db_path",
        "ACTIONTRACK_EMAIL_DOMAIN": "email_domain",
        "ACTIONTRACK_FUZZY_THRESHOLD": "fuzzy_threshold",
        "ACTIONTRACK_DATE_ORDER": "date_order",
    }
)

# TOML (section, key) → Config field. A `None` section means the top level.
_FILE_KEYS: Mapping[tuple[str | None, str], str] = MappingProxyType(
    {
        (None, "db_path"): "db_path",
        (None, "outbox_dir"): "outbox_dir",
        ("email", "domain"): "email_domain",
        ("email", "sign_off"): "sign_off",
        ("dedup", "fuzzy_threshold"): "fuzzy_threshold",
        ("dedup", "fuzzy_enabled"): "fuzzy_enabled",
        ("parsing", "date_order"): "date_order",
    }
)

_DEFAULT_ARG_NAMES: Mapping[str, str] = MappingProxyType(
    {"to": "to", "subject": "subject", "body": "body"}
)

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


@dataclass(frozen=True)
class McpConfig:
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    draft_tool: str = "create_draft"
    arg_names: Mapping[str, str] = field(default_factory=lambda: _DEFAULT_ARG_NAMES)
    to_as_list: bool = False
    timeout_s: float = 30.0


@dataclass(frozen=True)
class Config:
    db_path: Path
    outbox_dir: Path
    email_domain: str = "coditas.com"
    sign_off: str = "Thanks"
    fuzzy_enabled: bool = True
    fuzzy_threshold: int = 88  # 0..100
    date_order: DateOrder = "DMY"
    gmail_mcp: McpConfig = field(default_factory=McpConfig)
    sources: Mapping[str, Source] = field(default_factory=dict)  # where each key came from


SETTING_KEYS: tuple[str, ...] = (
    "db_path",
    "outbox_dir",
    "email_domain",
    "sign_off",
    "fuzzy_enabled",
    "fuzzy_threshold",
    "date_order",
    "gmail_mcp",
)


def default_paths() -> tuple[Path, Path, Path]:
    """(config_file, db_path, outbox_dir) in the OS-native locations."""
    config_dir = Path(platformdirs.user_config_dir(APP_NAME, appauthor=False, roaming=True))
    data_dir = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
    return config_dir / "config.toml", data_dir / "actiontrack.db", data_dir / "outbox"


def load_config(
    *, flags: Mapping[str, Any], env: Mapping[str, str], config_path: Path | None
) -> Config:
    """Merge all layers. `flags` maps Config field names to values; `None` means "not given"."""
    default_file, default_db, default_outbox = default_paths()
    values: dict[str, Any] = {"db_path": default_db, "outbox_dir": default_outbox}
    sources: dict[str, Source] = dict.fromkeys(SETTING_KEYS, "default")

    if config_path is not None and not config_path.is_file():
        raise UserInputError(
            f"config file not found: {config_path}", hint="check the --config path"
        )
    file_path = config_path if config_path is not None else default_file
    if file_path.is_file():
        for key, value in _read_file(file_path).items():
            values[key] = value
            sources[key] = "file"

    for env_name, key in ENV_KEYS.items():
        raw = env.get(env_name)
        if raw:
            values[key] = _coerce(key, raw, f"environment variable {env_name}")
            sources[key] = "env"

    for key, value in flags.items():
        if value is None:
            continue
        if key not in SETTING_KEYS or key == "gmail_mcp":
            raise ValueError(f"unknown config flag {key!r}")
        values[key] = _coerce(key, value, "command-line flag")
        sources[key] = "flag"

    return Config(**values, sources=MappingProxyType(sources))


def settings_view(config: Config) -> dict[str, tuple[Any, Source]]:
    """Each effective setting as (value, source), for `config show`."""
    return {key: (getattr(config, key), config.sources.get(key, "default")) for key in SETTING_KEYS}


def _read_file(path: Path) -> dict[str, Any]:
    where = f"config file {path}"
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise UserInputError(f"malformed TOML in {where}: {e}") from e
    except OSError as e:
        raise UserInputError(f"cannot read {where}: {e.strerror or e}") from e

    out: dict[str, Any] = {}
    for (section, name), key in _FILE_KEYS.items():
        table: Any = data if section is None else data.get(section, {})
        if not isinstance(table, dict):
            raise UserInputError(f"[{section}] must be a table in {where}")
        if name in table:
            label = name if section is None else f"{section}.{name}"
            out[key] = _coerce(key, table[name], f"{where} (key {label})")
    mcp = data.get("gmail_mcp")
    if mcp is not None:
        if not isinstance(mcp, dict):
            raise UserInputError(f"[gmail_mcp] must be a table in {where}")
        out["gmail_mcp"] = _parse_mcp(mcp, where)
    return out


def _coerce(key: str, value: Any, where: str) -> Any:
    """Validate and convert one setting. String input (env, flags) is parsed."""

    def bad(expected: str) -> UserInputError:
        return UserInputError(f"invalid value {value!r} for {key} in {where}: expected {expected}")

    if key in ("db_path", "outbox_dir"):
        if not isinstance(value, str | Path) or str(value) == "":
            raise bad("a path")
        return Path(value).expanduser()
    if key == "email_domain":
        if not isinstance(value, str) or not value.strip().lstrip("@"):
            raise bad("a domain such as coditas.com")
        return value.strip().lstrip("@").lower()
    if key == "sign_off":
        if not isinstance(value, str):
            raise bad("a string")
        return value
    if key == "fuzzy_enabled":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in _TRUE + _FALSE:
            return value.strip().lower() in _TRUE
        raise bad("true or false")
    if key == "fuzzy_threshold":
        if isinstance(value, str):
            try:
                value = int(value.strip())
            except ValueError:
                raise bad("an integer between 0 and 100") from None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise bad("an integer between 0 and 100")
        return value
    if key == "date_order":
        if not isinstance(value, str) or value.strip().upper() not in ("DMY", "MDY"):
            raise bad("DMY or MDY")
        return value.strip().upper()
    raise ValueError(f"unknown config key {key!r}")


def _parse_mcp(table: Mapping[str, Any], where: str) -> McpConfig:
    def bad(name: str, expected: str) -> UserInputError:
        return UserInputError(
            f"invalid value {table[name]!r} for gmail_mcp.{name} in {where}: expected {expected}"
        )

    kwargs: dict[str, Any] = {}
    for name, value in table.items():
        if name == "transport":
            if value not in ("stdio", "http"):
                raise bad(name, '"stdio" or "http"')
        elif name in ("command", "url", "draft_tool"):
            if not isinstance(value, str) or not value:
                raise bad(name, "a non-empty string")
        elif name == "args":
            if not isinstance(value, list) or not all(isinstance(a, str) for a in value):
                raise bad(name, "a list of strings")
            value = tuple(value)
        elif name == "arg_names":
            if not isinstance(value, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()
            ):
                raise bad(name, "a table of strings")
            value = MappingProxyType({**_DEFAULT_ARG_NAMES, **value})
        elif name == "to_as_list":
            if not isinstance(value, bool):
                raise bad(name, "true or false")
        elif name == "timeout_s":
            if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                raise bad(name, "a positive number")
            value = float(value)
        else:
            raise UserInputError(f"unknown key gmail_mcp.{name} in {where}")
        kwargs[name] = value
    return McpConfig(**kwargs)
