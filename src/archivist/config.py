"""Configuration and secret resolution from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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


# Claude Code auth modes (how headless Claude Code authenticates to the gateway).
GATEWAY_KEY_AUTH = "gateway-key"  # default: static LITELLM_API_KEY as ANTHROPIC_API_KEY
LOCAL_CLAUDE_AUTH = "local-claude"  # opt-in: defer to the operator's own Claude Code auth
_VALID_AUTH_MODES: frozenset[str] = frozenset({GATEWAY_KEY_AUTH, LOCAL_CLAUDE_AUTH})
CLAUDE_AUTH_MODE_ENV = "CLAUDE_AUTH_MODE"


def resolve_claude_auth_mode(
    environ: dict[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
) -> str:
    """Resolve the Claude Code auth mode; defaults to ``gateway-key``.

    ``gateway-key`` (default): the borrowed/static ``LITELLM_API_KEY`` is passed to Claude
    Code as ``ANTHROPIC_API_KEY`` against the gateway base URL. ``local-claude`` is an
    opt-in that defers to the operator's own Claude Code CLI auth (the enterprise
    ``apiKeyHelper``), so no long-lived engine key is required.
    """
    env = dict(environ if environ is not None else os.environ)
    dotenv = load_dotenv(dotenv_path or _repo_root() / ".env")
    raw = _strip_quotes(env.get(CLAUDE_AUTH_MODE_ENV) or dotenv.get(CLAUDE_AUTH_MODE_ENV, ""))
    mode = raw or GATEWAY_KEY_AUTH
    if mode not in _VALID_AUTH_MODES:
        expected = ", ".join(sorted(_VALID_AUTH_MODES))
        raise ConfigError(f"invalid {CLAUDE_AUTH_MODE_ENV}: {raw!r} (expected one of: {expected})")
    return mode


def resolve_agent_model(
    environ: dict[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
) -> str:
    """Resolve just the model id (for ``local-claude`` mode, where no gateway key is needed)."""
    env = dict(environ if environ is not None else os.environ)
    dotenv = load_dotenv(dotenv_path or _repo_root() / ".env")

    def get(name: str) -> str:
        return _strip_quotes(env.get(name) or dotenv.get(name, ""))

    model = get("ACT_CLAUDE_MODEL") or get("LITELLM_MODEL") or get("ANTHROPIC_MODEL")
    if not model:
        raise ConfigError(
            "missing configuration: set ACT_CLAUDE_MODEL (or LITELLM_MODEL) "
            "to a model id your Claude Code access can reach"
        )
    return model


@dataclass(frozen=True)
class LiteLLMConfig:
    """LiteLLM gateway settings resolved at call time from env refs."""

    api_base: str
    api_key: str
    model: str

    @property
    def anthropic_base_url(self) -> str:
        return self.api_base.rstrip("/")

    @property
    def anthropic_api_key(self) -> str:
        return self.api_key


_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("api_base", "LITELLM_API_BASE"),
    ("api_key", "LITELLM_API_KEY"),
    ("model", "LITELLM_MODEL"),
)


def resolve_litellm_config(
    *,
    environ: dict[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> LiteLLMConfig:
    """Resolve LiteLLM config; fail with every missing variable named at once."""
    env = dict(environ or os.environ)
    dotenv = load_dotenv(dotenv_path or _repo_root() / ".env")

    def get(name: str) -> str:
        return _strip_quotes(env.get(name) or dotenv.get(name, ""))

    values = {
        "api_base": get("LITELLM_API_BASE") or get("ANTHROPIC_BASE_URL"),
        "api_key": get("LITELLM_API_KEY") or get("ANTHROPIC_API_KEY"),
        "model": get("LITELLM_MODEL") or get("ACT_CLAUDE_MODEL"),
    }
    missing = []
    if not values["api_base"]:
        missing.append("LITELLM_API_BASE or ANTHROPIC_BASE_URL")
    if not values["api_key"]:
        missing.append("LITELLM_API_KEY or ANTHROPIC_API_KEY")
    if not values["model"]:
        missing.append("LITELLM_MODEL or ACT_CLAUDE_MODEL")
    if missing:
        raise ConfigError(f"missing configuration: {', '.join(missing)}")
    return LiteLLMConfig(
        api_base=values["api_base"],
        api_key=values["api_key"],
        model=values["model"],
    )


class ConfigError(Exception):
    """Raised when required configuration is absent or invalid."""
