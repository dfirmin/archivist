"""Auth resolution: each mode sets what Claude Code needs and removes what would misroute it."""

from __future__ import annotations

from pathlib import Path

import pytest

from archivist.claude_runner import build_claude_argv
from archivist.config import ConfigError, resolve_auth

GATEWAY_LEFTOVERS = {
    "ANTHROPIC_BASE_URL": "https://litellm.example.com",
    "ANTHROPIC_AUTH_TOKEN": "gateway-bearer",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "LITELLM_API_KEY": "gateway-key",
}


def resolve(env: dict[str, str], tmp_path: Path):  # type: ignore[no-untyped-def]
    return resolve_auth(env, dotenv_path=tmp_path / "absent.env")


def test_anthropic_api_goes_direct_and_strips_gateway_settings(tmp_path: Path) -> None:
    env = {"CLAUDE_AUTH_MODE": "anthropic-api", "ANTHROPIC_API_KEY": "sk-direct", **GATEWAY_LEFTOVERS}
    auth = resolve(env, tmp_path)
    out = auth.apply(env)
    assert auth.endpoint == "https://api.anthropic.com"
    assert out["ANTHROPIC_API_KEY"] == "sk-direct"
    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"):
        assert key not in out
    assert "sk-direct" not in auth.describe()


def test_anthropic_api_needs_its_own_key_not_the_gateway_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        resolve({"CLAUDE_AUTH_MODE": "anthropic-api", "LITELLM_API_KEY": "gateway-key"}, tmp_path)


def test_anthropic_api_model_is_optional(tmp_path: Path) -> None:
    auth = resolve({"CLAUDE_AUTH_MODE": "anthropic-api", "ANTHROPIC_API_KEY": "k"}, tmp_path)
    assert auth.model is None
    assert "--model" not in build_claude_argv(model=auth.model, agent="conductor")
    pinned = resolve({"CLAUDE_AUTH_MODE": "anthropic-api", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_MODEL": "m"}, tmp_path)
    assert build_claude_argv(model=pinned.model, agent="conductor")[5:7] == ["--model", "m"]


def test_gateway_key_routes_through_the_gateway(tmp_path: Path) -> None:
    env = {"LITELLM_API_BASE": "https://gw.example.com/", "LITELLM_API_KEY": "gk", "LITELLM_MODEL": "m"}
    out = resolve(env, tmp_path).apply(env)
    assert out["ANTHROPIC_BASE_URL"] == "https://gw.example.com"
    assert out["ANTHROPIC_API_KEY"] == "gk"
    assert out["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] == "1"


def test_gateway_key_names_everything_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="LITELLM_API_BASE.*LITELLM_API_KEY.*LITELLM_MODEL"):
        resolve({}, tmp_path)


def test_local_claude_defers_to_the_api_key_helper(tmp_path: Path) -> None:
    env = {"CLAUDE_AUTH_MODE": "local-claude", "ACT_CLAUDE_MODEL": "m", "ANTHROPIC_API_KEY": "stale"}
    out = resolve(env, tmp_path).apply(env)
    assert "ANTHROPIC_API_KEY" not in out


def test_inherit_changes_nothing(tmp_path: Path) -> None:
    env = {"CLAUDE_AUTH_MODE": "inherit", "ANTHROPIC_BASE_URL": "https://host-proxy", "CLAUDE_CODE_OAUTH_TOKEN": "t"}
    auth = resolve(env, tmp_path)
    assert auth.apply(env) == env
    assert auth.model is None


def test_unknown_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="expected one of: gateway-key, anthropic-api, local-claude, inherit"):
        resolve({"CLAUDE_AUTH_MODE": "bedrock"}, tmp_path)
