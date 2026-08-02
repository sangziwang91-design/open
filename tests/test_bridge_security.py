import os
import stat
from pathlib import Path

from agentbridge.bridge.controller import filtered_bridge_environment
from agentbridge.bridge.security import load_or_create_token
from agentbridge.executors.opencode import _policy, _runtime_environment


def test_token_is_created_once_and_reused(tmp_path: Path) -> None:
    path = tmp_path / "private" / "bridge.token"
    first, created = load_or_create_token(path)
    second, created_again = load_or_create_token(path)
    assert created
    assert not created_again
    assert first == second
    assert len(first) >= 32
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_bridge_opencode_environment_drops_unapproved_secrets(monkeypatch) -> None:
    monkeypatch.setenv("AGENTBRIDGE_TEST_SECRET", "must-not-leak")
    monkeypatch.setenv("PATH", "/safe/bin")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"model":"should-not-be-inherited"}')
    environment = _runtime_environment(_policy(), frozenset({"PATH"}))
    assert environment["PATH"] == "/safe/bin"
    assert "AGENTBRIDGE_TEST_SECRET" not in environment
    config = environment["OPENCODE_CONFIG_CONTENT"]
    assert "should-not-be-inherited" not in config
    assert "permission" in config


def test_operator_can_explicitly_inherit_provider_configuration(monkeypatch) -> None:
    monkeypatch.setenv("PROVIDER_API_KEY", "configured-by-operator")
    environment = _runtime_environment(_policy(), frozenset({"PROVIDER_API_KEY"}))
    assert environment["PROVIDER_API_KEY"] == "configured-by-operator"


def test_bridge_verification_environment_uses_same_secret_allowlist(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTBRIDGE_TEST_SECRET", "must-not-leak")
    monkeypatch.setenv("PATH", "/safe/bin")
    filtered = filtered_bridge_environment()
    assert filtered["PATH"] == "/safe/bin"
    assert "AGENTBRIDGE_TEST_SECRET" not in filtered
