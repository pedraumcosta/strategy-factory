"""The .env loader: the keys' one home is read at every entry point, a
shell export always beats the file, and nothing secret is ever tracked
(.gitignore keeps .env out; only .env.example is committed)."""

import subprocess
from pathlib import Path

from factory.env import ROOT, load_env


def test_loads_keys_and_never_overrides_the_shell(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n"
        "\n"
        "NIXTLA_API_KEY=abc123\n"
        "export TYPESAFE_API_KEY='quoted value'\n"
        "ALREADY_SET=from_file\n"
        "BLANK_SLOT=\n"
        "not a key-value line\n")
    env = {"ALREADY_SET": "from_shell"}
    loaded = load_env(f, environ=env)
    assert loaded == ["NIXTLA_API_KEY", "TYPESAFE_API_KEY"]
    assert env["NIXTLA_API_KEY"] == "abc123"
    assert env["TYPESAFE_API_KEY"] == "quoted value"   # export + quotes stripped
    assert env["ALREADY_SET"] == "from_shell"          # the shell wins
    # an unfilled .env.example slot must not shadow the SDK's login fallback
    assert "BLANK_SLOT" not in env


def test_missing_file_is_a_quiet_noop(tmp_path):
    env: dict[str, str] = {}
    assert load_env(tmp_path / "nope", environ=env) == []
    assert env == {}


def test_env_file_is_ignored_and_example_is_tracked():
    out = subprocess.run(
        ["git", "check-ignore", ".env"], cwd=ROOT,
        capture_output=True, text=True)
    assert out.returncode == 0, ".env must be gitignored"
    out = subprocess.run(
        ["git", "check-ignore", ".env.example"], cwd=ROOT,
        capture_output=True, text=True)
    assert out.returncode != 0, ".env.example must be committable"
    assert (Path(ROOT) / ".env.example").exists()
