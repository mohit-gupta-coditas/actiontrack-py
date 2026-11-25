from __future__ import annotations

from pathlib import Path

import pytest

from actiontrack.config import Config, McpConfig, default_paths, load_config, settings_view
from actiontrack.errors import UserInputError


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_TC_M0_06_env_beats_file_beats_default(tmp_path: Path) -> None:
    cfg = write(tmp_path / "c.toml", "[dedup]\nfuzzy_threshold = 80\n")
    config = load_config(
        flags={"db_path": None}, env={"ACTIONTRACK_FUZZY_THRESHOLD": "85"}, config_path=cfg
    )
    assert config.fuzzy_threshold == 85
    assert config.sources["fuzzy_threshold"] == "env"


def test_TC_M0_07_flag_beats_file(tmp_path: Path) -> None:
    cfg = write(tmp_path / "c.toml", 'db_path = "from-file.db"\n')
    config = load_config(flags={"db_path": tmp_path / "flag.db"}, env={}, config_path=cfg)
    assert config.db_path == tmp_path / "flag.db"
    assert config.sources["db_path"] == "flag"


def test_TC_M0_08_defaults_when_no_file(isolated_env: Path) -> None:
    config = load_config(flags={}, env={}, config_path=None)
    assert config == Config(
        db_path=isolated_env / "data" / "actiontrack" / "actiontrack.db",
        outbox_dir=isolated_env / "data" / "actiontrack" / "outbox",
        sources=config.sources,
    )
    assert set(config.sources.values()) == {"default"}
    assert config.gmail_mcp == McpConfig()
    cfg_file, _, _ = default_paths()
    assert cfg_file == isolated_env / "config" / "actiontrack" / "config.toml"


def test_default_config_file_is_read(isolated_env: Path) -> None:
    write(isolated_env / "config" / "actiontrack" / "config.toml", '[email]\ndomain = "x.io"\n')
    config = load_config(flags={}, env={}, config_path=None)
    assert (config.email_domain, config.sources["email_domain"]) == ("x.io", "file")


def test_TC_M0_09_missing_explicit_config_file(tmp_path: Path) -> None:
    with pytest.raises(UserInputError, match=r"missing\.toml"):
        load_config(flags={}, env={}, config_path=tmp_path / "missing.toml")


def test_TC_M0_10_threshold_out_of_range_names_key_and_file(tmp_path: Path) -> None:
    cfg = write(tmp_path / "c.toml", "[dedup]\nfuzzy_threshold = 150\n")
    with pytest.raises(UserInputError) as exc:
        load_config(flags={}, env={}, config_path=cfg)
    assert "fuzzy_threshold" in exc.value.message
    assert str(cfg) in exc.value.message


def test_full_file_layout(tmp_path: Path) -> None:
    cfg = write(
        tmp_path / "c.toml",
        """
db_path = "~/at.db"
outbox_dir = "out"

[email]
domain = "@Example.ORG"
sign_off = "Thanks,\\nMohit"

[dedup]
fuzzy_threshold = 90
fuzzy_enabled = false

[parsing]
date_order = "mdy"

[gmail_mcp]
transport = "http"
url = "http://localhost:9000/mcp"
args = ["--a"]
arg_names = { to = "recipients" }
to_as_list = false
timeout_s = 5
""",
    )
    config = load_config(flags={}, env={}, config_path=cfg)
    assert config.db_path == Path("~/at.db").expanduser()
    assert config.outbox_dir == Path("out")
    assert config.email_domain == "example.org"
    assert config.sign_off == "Thanks,\nMohit"
    assert (config.fuzzy_threshold, config.fuzzy_enabled, config.date_order) == (90, False, "MDY")
    mcp = config.gmail_mcp
    assert (mcp.transport, mcp.url, mcp.args, mcp.to_as_list, mcp.timeout_s) == (
        "http",
        "http://localhost:9000/mcp",
        ("--a",),
        False,
        5.0,
    )
    assert dict(mcp.arg_names) == {"to": "recipients", "subject": "subject", "body": "body"}
    assert all(src == "file" for src in config.sources.values())


def test_env_overrides_every_env_key(tmp_path: Path) -> None:
    env = {
        "ACTIONTRACK_DB": str(tmp_path / "env.db"),
        "ACTIONTRACK_EMAIL_DOMAIN": "env.io",
        "ACTIONTRACK_FUZZY_THRESHOLD": "70",
        "ACTIONTRACK_DATE_ORDER": "MDY",
    }
    config = load_config(flags={}, env=env, config_path=None)
    assert (config.db_path, config.email_domain, config.fuzzy_threshold, config.date_order) == (
        tmp_path / "env.db",
        "env.io",
        70,
        "MDY",
    )
    view = settings_view(config)
    assert {k for k, (_, src) in view.items() if src == "env"} == {
        "db_path",
        "email_domain",
        "fuzzy_threshold",
        "date_order",
    }


@pytest.mark.parametrize(
    ("env", "fragment"),
    [
        ({"ACTIONTRACK_FUZZY_THRESHOLD": "high"}, "ACTIONTRACK_FUZZY_THRESHOLD"),
        ({"ACTIONTRACK_FUZZY_THRESHOLD": "101"}, "fuzzy_threshold"),
        ({"ACTIONTRACK_DATE_ORDER": "YMD"}, "ACTIONTRACK_DATE_ORDER"),
        ({"ACTIONTRACK_EMAIL_DOMAIN": "@"}, "email_domain"),
    ],
)
def test_invalid_env_values(env: dict[str, str], fragment: str) -> None:
    with pytest.raises(UserInputError, match=fragment):
        load_config(flags={}, env=env, config_path=None)


@pytest.mark.parametrize(
    ("toml", "fragment"),
    [
        ("[dedup\n", "malformed TOML"),
        ("dedup = 3\n", r"\[dedup\] must be a table"),
        ("[dedup]\nfuzzy_threshold = true\n", "fuzzy_threshold"),
        ('[dedup]\nfuzzy_enabled = "maybe"\n', "fuzzy_enabled"),
        ("[email]\nsign_off = 3\n", "sign_off"),
        ("db_path = 3\n", "db_path"),
        ("gmail_mcp = 1\n", r"\[gmail_mcp\] must be a table"),
        ('[gmail_mcp]\ntransport = "smtp"\n', "gmail_mcp.transport"),
        ("[gmail_mcp]\ncommand = 1\n", "gmail_mcp.command"),
        ('[gmail_mcp]\nargs = "x"\n', "gmail_mcp.args"),
        ("[gmail_mcp]\narg_names = { to = 1 }\n", "gmail_mcp.arg_names"),
        ('[gmail_mcp]\nto_as_list = "yes"\n', "gmail_mcp.to_as_list"),
        ("[gmail_mcp]\ntimeout_s = 0\n", "gmail_mcp.timeout_s"),
        ("[gmail_mcp]\nsend_tool = 'send'\n", "unknown key gmail_mcp.send_tool"),
    ],
)
def test_invalid_file_values(tmp_path: Path, toml: str, fragment: str) -> None:
    cfg = write(tmp_path / "c.toml", toml)
    with pytest.raises(UserInputError, match=fragment):
        load_config(flags={}, env={}, config_path=cfg)


def test_string_bool_coercion_for_flags() -> None:
    config = load_config(flags={"fuzzy_enabled": "off"}, env={}, config_path=None)
    assert config.fuzzy_enabled is False
    assert config.sources["fuzzy_enabled"] == "flag"


def test_unknown_flag_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown config flag"):
        load_config(flags={"nope": 1}, env={}, config_path=None)
