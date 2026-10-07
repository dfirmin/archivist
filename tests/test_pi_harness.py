"""The Pi harness (ADR 0008): install layout, auth → provider, stream parsing, and the plumbing
end to end against a scripted endpoint. Nothing here judges an agent; live runs do that."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from archivist.config import ConfigError, resolve_auth
from archivist.engine import load_engine
from archivist.errors import DefinitionError
from archivist.harness import CLAUDE_CODE, PI, ClaudeCodeHarness, get_harness, harness_name
from archivist.pi_harness import ALL_TOOLS, GATEWAY_PROVIDER, PiHarness, agent_prompt, pi_tools, provider_for
from archivist.pi_stream import PiStreamMonitor
from mock_anthropic import MockAnthropic

NO_DOTENV = Path("/nonexistent/.env")


def _auth(env: dict[str, str]):
    return resolve_auth(env, dotenv_path=NO_DOTENV)


# ------------------------------------------------------------------------- selection


def test_harness_defaults_to_claude_code_and_refuses_unknown() -> None:
    assert harness_name({}) == CLAUDE_CODE
    assert isinstance(get_harness({}), ClaudeCodeHarness)
    assert get_harness({"ARCHIVIST_HARNESS": "pi"}).name == PI
    with pytest.raises(ConfigError, match="ARCHIVIST_HARNESS"):
        harness_name({"ARCHIVIST_HARNESS": "opencode"})


# --------------------------------------------------------------------------- install


def test_tools_map_to_pi_names_and_unknown_tools_are_refused() -> None:
    assert pi_tools(("Read", "Bash", "Glob", "Skill")) == ("read", "bash", "find", "ls", "Skill")
    assert pi_tools(("Agent(author, verifier)", "TodoWrite")) == ("Agent", "TodoWrite")
    assert pi_tools(()) == ALL_TOOLS and "Agent" not in ALL_TOOLS  # sub-agents never spawn
    with pytest.raises(DefinitionError, match="no Pi equivalent"):
        pi_tools(("WebFetch",))


def test_preloaded_skills_are_appended_to_the_agent_prompt() -> None:
    engine = load_engine()
    author = engine.agents["author"]
    prompt = agent_prompt(author, engine.skills)
    assert prompt.startswith(author.body.strip()[:80])
    for name in author.skills:
        assert f'<skill name="{name}">' in prompt
        assert engine.skills[name].body.strip()[:80] in prompt


def test_install_writes_specs_skills_and_extension(tmp_path: Path) -> None:
    engine = load_engine()
    harness = PiHarness()
    written = harness.install(tmp_path, engine, spawnable=("author", "verifier"))
    root = tmp_path / ".claude" / "pi"
    assert set(written) == set(engine.agents)
    assert (root / "extensions" / "archivist.ts").is_file()
    assert (root / "skills" / "target-contracts" / "SKILL.md").is_file()
    conductor = json.loads((root / "agents" / "conductor.json").read_text())
    assert "Agent" in conductor["tools"] and conductor["model"]
    assert Path(conductor["prompt_file"]).is_file()
    gap = json.loads((root / "agents" / "gap-agent.json").read_text())
    assert "Agent" not in gap["tools"]


# ------------------------------------------------------------------------------ auth


def test_anthropic_api_uses_the_builtin_provider(tmp_path: Path) -> None:
    auth = _auth({"CLAUDE_AUTH_MODE": "anthropic-api", "ANTHROPIC_API_KEY": "k"})
    provider = provider_for(auth, auth.apply({}), ("claude-sonnet-5-5", "claude-haiku-4-5-20251001"))
    assert provider.name == "anthropic"
    overrides = provider.models_json["providers"]["anthropic"]["modelOverrides"]
    assert overrides == {"claude-sonnet-5-5": {"compat": {"forceAdaptiveThinking": True}}}


def test_gateway_key_writes_a_provider_with_every_agent_model() -> None:
    env = {"CLAUDE_AUTH_MODE": "gateway-key", "LITELLM_API_BASE": "https://gw.example/", "LITELLM_API_KEY": "k",
           "LITELLM_MODEL": "claude-sonnet-5-5"}
    auth = _auth(env)
    provider = provider_for(auth, auth.apply(env), ("claude-sonnet-5-5", "claude-haiku-4-5-20251001"))
    spec = provider.models_json["providers"][GATEWAY_PROVIDER]
    assert provider.name == GATEWAY_PROVIDER
    assert spec["baseUrl"] == "https://gw.example" and spec["apiKey"] == "$ANTHROPIC_API_KEY"
    assert [m["id"] for m in spec["models"]] == ["claude-sonnet-5-5", "claude-haiku-4-5-20251001"]
    assert spec["models"][0]["compat"] == {"forceAdaptiveThinking": True}  # the model decides, as on Claude Code
    assert "compat" not in spec["models"][1]
    assert spec["headers"] == {"anthropic-beta": ""}  # betas off by default, as for Claude Code


def test_local_claude_uses_the_key_helper_per_request(tmp_path: Path) -> None:
    helper = tmp_path / "helper.sh"
    helper.write_text("#!/bin/sh\necho k\n")
    helper.chmod(0o755)
    env = {"CLAUDE_AUTH_MODE": "local-claude", "ACT_CLAUDE_MODEL": "claude-sonnet-5-5",
           "ANTHROPIC_BASE_URL": "https://gw.example", "CLAUDE_LOCAL_API_KEY_HELPER": str(helper)}
    auth = _auth(env)
    spec = provider_for(auth, auth.apply(env), ()).models_json["providers"][GATEWAY_PROVIDER]
    assert spec["apiKey"] == f"!{helper}"
    del env["ANTHROPIC_BASE_URL"]
    with pytest.raises(ConfigError, match="ANTHROPIC_BASE_URL"):
        provider_for(_auth(env), env, ())


# ---------------------------------------------------------------------------- stream


def _monitor(tmp_path: Path, **kw) -> PiStreamMonitor:  # type: ignore[no-untyped-def]
    import io

    return PiStreamMonitor(out=io.StringIO(), err=io.StringIO(), events_dir=tmp_path, **kw)


def _system(*tools: str) -> str:
    return json.dumps({"type": "message_end", "message": {"role": "system", "toolsAdded": [{"name": t} for t in tools]}})


def test_missing_agent_tool_aborts_before_any_work(tmp_path: Path) -> None:
    monitor = _monitor(tmp_path, required_agents=("author",))
    monitor.feed(_system("read", "bash"))
    assert monitor.abort_reason and "extension did not load" in monitor.abort_reason


def test_a_failed_response_is_an_error_although_pi_exits_zero(tmp_path: Path) -> None:
    monitor = _monitor(tmp_path)
    monitor.feed(json.dumps({"type": "message_end", "message": {
        "role": "assistant", "content": [], "stopReason": "error", "errorMessage": "429"}}))
    monitor.feed(json.dumps({"type": "agent_end", "messages": []}))
    assert monitor.saw_result and monitor.is_error


def test_dispatch_results_and_child_cost_are_read_from_tool_events(tmp_path: Path) -> None:
    monitor = _monitor(tmp_path)
    monitor.feed(json.dumps({"type": "tool_execution_start", "toolCallId": "t1", "toolName": "Agent",
                             "args": {"subagent_type": "intake-planner", "description": "plan-inbox", "prompt": "p"}}))
    monitor.feed(json.dumps({"type": "tool_execution_end", "toolCallId": "t1", "toolName": "Agent", "isError": False,
                             "result": {"content": [{"type": "text", "text": "Groups: 0"}],
                                        "details": {"usage": {"cost": 0.25, "input": 10}}}}))
    assert monitor.dispatched_agents == ("intake-planner",)
    assert monitor.results["t1"] == "Groups: 0"
    assert monitor.cost == pytest.approx(0.25)


# ------------------------------------------------------------------- end to end (mock)


@pytest.mark.skipif(shutil.which("pi") is None, reason="pi is not installed")
def test_pi_session_spawns_a_parallel_fleet_with_preloaded_skills(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from archivist.claude_runner import launch_claude

    monkeypatch.setenv("CHILD_SESSION_TRANSCRIPT_DIR", str(tmp_path / "transcripts"))
    with MockAnthropic(child_delay=1.0) as mock:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        harness = PiHarness()
        written = harness.install(workspace, load_engine(), spawnable=("gap-agent",))
        env = {"PATH": __import__("os").environ["PATH"], "HOME": str(tmp_path),
               "CLAUDE_AUTH_MODE": "gateway-key", "LITELLM_API_BASE": mock.url, "LITELLM_API_KEY": "mock",
               "LITELLM_MODEL": "claude-sonnet-5-5"}
        auth = _auth(env)
        session_env = harness.session_env(auth.apply(env), auth, workspace)
        monitor = harness.monitor(required_agents=written, workspace=workspace)
        code = launch_claude(
            harness.argv(model="claude-sonnet-5-5", workspace=workspace,
                         system_prompt="MOCK-SUPERVISOR MOCK-AGENT=gap-agent"),
            env=session_env, cwd=workspace, prompt="Begin.", monitor=monitor,
        )
        transcripts = monitor.write_transcripts(workspace)

    assert code == 0
    assert monitor.dispatched_agents == ("gap-agent",) and len(monitor.dispatches) == 2
    assert all(r == "SMOKE_OK PRELOAD" for r in monitor.results.values())
    assert mock.max_in_flight_children == 2  # one message, two spawns, run together
    children = [r for r in mock.requests if r["child"]]
    assert {r["model"] for r in children} == {"claude-haiku-4-5-20251001"}  # the agent's pin
    assert all("Agent" not in r["tools"] for r in children)
    assert all(r["headers"].get("x-api-key") == "mock" for r in mock.requests)
    assert all(r["thinking"]["type"] == "enabled" and r["thinking"]["budget_tokens"] == 31_999
               for r in children)  # Haiku: budgeted, as Claude Code sends it
    assert all(r["thinking"]["display"] == "omitted" for r in mock.requests)  # as Claude Code asks
    assert all(r["thinking"]["type"] == "adaptive" for r in mock.requests if not r["child"])  # Sonnet
    assert len([p for p in transcripts if "gap-agent" in p.name]) == 2


@pytest.mark.skipif(shutil.which("pi") is None, reason="pi is not installed")
def test_agent_outside_the_roster_is_refused(tmp_path: Path) -> None:
    from archivist.claude_runner import launch_claude

    with MockAnthropic() as mock:
        harness = PiHarness()
        harness.install(tmp_path, load_engine(), spawnable=("verifier",))
        env = {"PATH": __import__("os").environ["PATH"], "HOME": str(tmp_path),
               "CLAUDE_AUTH_MODE": "gateway-key", "LITELLM_API_BASE": mock.url, "LITELLM_API_KEY": "mock",
               "LITELLM_MODEL": "claude-sonnet-5-5"}
        auth = _auth(env)
        monitor = harness.monitor(required_agents=(), workspace=tmp_path)
        launch_claude(
            harness.argv(model="claude-sonnet-5-5", workspace=tmp_path,
                         system_prompt="MOCK-SUPERVISOR MOCK-AGENT=author"),
            env=harness.session_env(auth.apply(env), auth, tmp_path), cwd=tmp_path, prompt="Begin.",
            monitor=monitor,
        )
    assert not [r for r in mock.requests if r["child"]]  # nothing was spawned
    assert all("not in this run's roster" in r for r in monitor.results.values())


def test_thinking_matches_claude_code(tmp_path: Path) -> None:
    PiHarness().install(tmp_path, load_engine(), spawnable=())
    settings = json.loads((tmp_path / ".claude" / "pi" / "settings.json").read_text())
    assert settings["modelThinkingLevels"]["anthropic/claude-haiku-4-5-20251001"] == "high"
    assert settings["thinkingBudgets"] == {"high": 31_999}  # Claude Code's Haiku sub-agent budget
    assert not any("sonnet" in key for key in settings["modelThinkingLevels"])  # adaptive instead
