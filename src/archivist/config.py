"""How headless Claude Code authenticates, resolved from the environment and ``.env``.

Four modes, chosen with ``CLAUDE_AUTH_MODE``:

- ``gateway-key`` (default) — a LiteLLM (or other Anthropic-compatible) gateway.
  ``LITELLM_API_KEY`` is sent as ``ANTHROPIC_API_KEY`` to ``LITELLM_API_BASE``. Pre-release
  beta headers are stripped, because gateways commonly reject them.
- ``anthropic-api`` — the Anthropic API directly. ``ANTHROPIC_API_KEY`` is sent to the
  default endpoint (api.anthropic.com). Any gateway URL, bearer token or beta stripping
  inherited from the environment is removed, so a stray gateway setting cannot hijack the run.
- ``local-claude`` — the operator's own Claude Code login (an ``apiKeyHelper``), local dev only.
- ``inherit`` — whatever auth the installed Claude Code already has (a ``/login``, a
  ``CLAUDE_CODE_OAUTH_TOKEN`` from ``claude setup-token``, or a host-provided session such
  as a Claude Code cloud environment). Archivist changes nothing.

``resolve_auth`` returns what to set and what to remove; ``AuthConfig.apply`` produces the
environment for the ``claude`` process. Secrets never appear in ``describe()``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from archivist.errors import ArchivistError

GATEWAY_KEY_AUTH = "gateway-key"
ANTHROPIC_API_AUTH = "anthropic-api"
LOCAL_CLAUDE_AUTH = "local-claude"
INHERIT_AUTH = "inherit"
AUTH_MODES = (GATEWAY_KEY_AUTH, ANTHROPIC_API_AUTH, LOCAL_CLAUDE_AUTH, INHERIT_AUTH)
CLAUDE_AUTH_MODE_ENV = "CLAUDE_AUTH_MODE"
ANTHROPIC_API_BASE = "https://api.anthropic.com"
_GATEWAY_ONLY = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS")


class ConfigError(ArchivistError):
    """Required configuration is absent or invalid."""


def _strip_quotes(value: str) -> str:
    return value.strip().strip("\"'")


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict, stripping wrapping quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = _strip_quotes(value)
    return values


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class AuthConfig:
    mode: str
    model: str | None
    endpoint: str
    set_env: dict[str, str] = field(default_factory=dict)
    unset_env: tuple[str, ...] = ()

    def apply(self, base_env: dict[str, str]) -> dict[str, str]:
        env = {k: v for k, v in base_env.items() if k not in self.unset_env}
        env.update(self.set_env)
        return env

    def describe(self) -> str:
        return f"auth      {self.mode} → {self.endpoint}"


def resolve_auth(
    environ: dict[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
) -> AuthConfig:
    """Resolve the auth mode and its settings; name every missing variable at once."""
    env = dict(environ if environ is not None else os.environ)
    dotenv = load_dotenv(dotenv_path or _repo_root() / ".env")

    def get(name: str) -> str:
        return _strip_quotes(env.get(name) or dotenv.get(name, ""))

    raw_mode = get(CLAUDE_AUTH_MODE_ENV)
    mode = raw_mode or GATEWAY_KEY_AUTH
    if mode not in AUTH_MODES:
        raise ConfigError(
            f"invalid {CLAUDE_AUTH_MODE_ENV}: {raw_mode!r} (expected one of: {', '.join(AUTH_MODES)})"
        )

    if mode == ANTHROPIC_API_AUTH:
        key = get("ANTHROPIC_API_KEY")
        if not key:
            raise ConfigError("missing configuration: ANTHROPIC_API_KEY (anthropic-api mode)")
        model = get("ACT_CLAUDE_MODEL") or get("ANTHROPIC_MODEL") or None
        set_env = {"ANTHROPIC_API_KEY": key}
        if model:
            set_env |= {"ANTHROPIC_MODEL": model, "ACT_CLAUDE_MODEL": model}
        return AuthConfig(mode, model, ANTHROPIC_API_BASE, set_env, _GATEWAY_ONLY)

    if mode == INHERIT_AUTH:
        model = get("ACT_CLAUDE_MODEL") or None
        set_env = {"ACT_CLAUDE_MODEL": model} if model else {}
        return AuthConfig(mode, model, "Claude Code's existing auth", set_env, ())

    if mode == LOCAL_CLAUDE_AUTH:
        model = get("ACT_CLAUDE_MODEL") or get("LITELLM_MODEL") or get("ANTHROPIC_MODEL")
        if not model:
            raise ConfigError("missing configuration: ACT_CLAUDE_MODEL (local-claude mode)")
        set_env = {
            "ANTHROPIC_MODEL": model,
            "ACT_CLAUDE_MODEL": model,
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        }
        endpoint = get("ANTHROPIC_BASE_URL") or get("LITELLM_API_BASE") or "apiKeyHelper default"
        return AuthConfig(mode, model, endpoint, set_env, ("ANTHROPIC_API_KEY",))

    base = get("LITELLM_API_BASE") or get("ANTHROPIC_BASE_URL")
    key = get("LITELLM_API_KEY")
    model = get("LITELLM_MODEL") or get("ACT_CLAUDE_MODEL")
    missing = [
        name
        for name, value in (
            ("LITELLM_API_BASE (or ANTHROPIC_BASE_URL)", base),
            ("LITELLM_API_KEY", key),
            ("LITELLM_MODEL (or ACT_CLAUDE_MODEL)", model),
        )
        if not value
    ]
    if missing:
        raise ConfigError(f"missing configuration (gateway-key mode): {', '.join(missing)}")
    set_env = {
        "ANTHROPIC_API_KEY": key,
        "ANTHROPIC_BASE_URL": base.rstrip("/"),
        "ANTHROPIC_MODEL": model,
        "ACT_CLAUDE_MODEL": model,
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    }
    return AuthConfig(mode, model, base.rstrip("/"), set_env, ("ANTHROPIC_AUTH_TOKEN",))
