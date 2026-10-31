"""Credential loading from .env: values load, existing env wins, values are never printed."""

import os

import pytest

from orchestrator.cli import main as orch
from orchestrator.fileio import is_private, load_env_file


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("ORCH_T_KEY", "ORCH_T_MODEL", "ORCH_T_QUOTED", "ORCH_T_EXPORTED"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_loads_values_and_reports_names_only(tmp_path, clean_env):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nORCH_T_KEY=sk-secret-123\nORCH_T_QUOTED=\"two words\"\nexport ORCH_T_EXPORTED='x'\n")
    assert load_env_file(env) == ["ORCH_T_KEY", "ORCH_T_QUOTED", "ORCH_T_EXPORTED"]
    assert os.environ["ORCH_T_KEY"] == "sk-secret-123"
    assert os.environ["ORCH_T_QUOTED"] == "two words" and os.environ["ORCH_T_EXPORTED"] == "x"


def test_existing_environment_wins(tmp_path, clean_env):
    clean_env.setenv("ORCH_T_MODEL", "from-shell")
    env = tmp_path / ".env"
    env.write_text("ORCH_T_MODEL=from-file\n")
    assert load_env_file(env) == []
    assert os.environ["ORCH_T_MODEL"] == "from-shell"


def test_missing_file_is_fine_and_malformed_line_is_an_error(tmp_path, clean_env):
    assert load_env_file(tmp_path / "absent.env") == []
    bad = tmp_path / ".env"
    bad.write_text("ORCH_T_KEY sk-oops\n")
    with pytest.raises(ValueError, match=":1: expected KEY=value"):
        load_env_file(bad)


def test_cli_never_prints_the_value_and_warns_on_loose_permissions(tmp_path, clean_env, capsys):
    env = tmp_path / ".env"
    env.write_text("ORCH_T_KEY=sk-super-secret\n")
    env.chmod(0o644)
    assert not is_private(env)
    orch(["--env-file", str(env), "--runs-dir", str(tmp_path), "pending", "no-run"])
    out = capsys.readouterr()
    assert "ORCH_T_KEY" in out.err and "chmod 600" in out.err
    assert "sk-super-secret" not in out.err + out.out

    env.chmod(0o600)
    assert is_private(env)
