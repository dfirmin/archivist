"""Read Claude Code's ``--output-format stream-json`` for one headless session.

One monitor per session. For every line it:

- prints operator-readable progress (assistant text, tool calls, sub-agent activity);
- notices ``Task`` calls — the conductor spawning a sub-agent — and labels the output of
  each sub-agent with its name;
- hands the redacted event to the transcript recorder;
- captures the session id and the final result.

It also fails fast: if the session's ``init`` event does not list every sub-agent the
run needs, the definitions did not load and nothing downstream can work. The monitor sets
``abort_reason`` and the launcher terminates the process before it spends any tokens.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from archivist.transcripts import TranscriptRecorder

# Claude Code has called the sub-agent tool both "Task" and "Agent".
SUBAGENT_TOOLS = frozenset({"Task", "Agent"})
_BRIEF_KEYS = (
    "command",
    "file_path",
    "path",
    "pattern",
    "skill",
    "subagent_type",
    "description",
    "query",
    "prompt",
)
_BRIEF_LIMIT = 110


def _brief(tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in _BRIEF_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            text = " ".join(value.split())
            return text if len(text) <= _BRIEF_LIMIT else text[: _BRIEF_LIMIT - 1] + "…"
    return ""


def _content_blocks(message: Any) -> list[dict[str, Any]]:
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", "")) for block in content if isinstance(block, dict)
        )
    return ""


def _token_detail(model_usage: Any) -> str:
    """Token totals across every model the session used (sub-agents included)."""
    if not isinstance(model_usage, dict) or not model_usage:
        return ""
    keys = (("inputTokens", "in"), ("outputTokens", "out"),
            ("cacheReadInputTokens", "cache_read"), ("cacheCreationInputTokens", "cache_write"))
    totals = dict.fromkeys((label for _, label in keys), 0)
    for usage in model_usage.values():
        if isinstance(usage, dict):
            for key, label in keys:
                value = usage.get(key)
                if isinstance(value, (int, float)):
                    totals[label] += int(value)
    return " tokens " + " ".join(f"{label}={value}" for label, value in totals.items())


@dataclass(slots=True)
class Dispatch:
    tool_use_id: str
    agent: str
    description: str | None


@dataclass(slots=True)
class StreamMonitor:
    required_agents: tuple[str, ...] = ()
    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)
    recorder: TranscriptRecorder = field(default_factory=TranscriptRecorder)

    session_id: str | None = None
    model: str | None = None
    init_agents: tuple[str, ...] = ()
    dispatches: dict[str, Dispatch] = field(default_factory=dict)
    results: dict[str, str] = field(default_factory=dict)
    final_text: str = ""
    result_subtype: str | None = None
    is_error: bool = False
    saw_result: bool = False
    abort_reason: str | None = None

    # -- public surface ----------------------------------------------------------

    @property
    def dispatched_agents(self) -> tuple[str, ...]:
        """Sub-agent names in first-seen order."""
        return tuple(dict.fromkeys(d.agent for d in self.dispatches.values()))

    def feed(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self._say(line)
            return
        if not isinstance(event, dict):
            return
        self.recorder.add_event(event)
        kind = event.get("type")
        if kind == "system":
            self._on_system(event)
        elif kind == "assistant":
            self._on_assistant(event)
        elif kind == "user":
            self._on_user(event)
        elif kind == "result":
            self._on_result(event)

    def write_transcripts(self, workspace: Path) -> list[Path]:
        return self.recorder.write(
            session_id=self.session_id or "session",
            workspace=workspace,
            results=self.results,
        )

    # -- output ------------------------------------------------------------------

    def _say(self, text: str = "", *, err: bool = False, prefix: str = "") -> None:
        stream = self.err if err else self.out
        stream.write(f"{prefix}{text}\n")
        stream.flush()

    def _label(self, event: dict[str, Any]) -> str:
        parent = event.get("parent_tool_use_id")
        if not isinstance(parent, str) or not parent:
            return ""
        dispatch = self.dispatches.get(parent)
        return f"  [{dispatch.agent if dispatch else 'sub-agent'}] "

    # -- events ------------------------------------------------------------------

    def _on_system(self, event: dict[str, Any]) -> None:
        if event.get("subtype") != "init":
            return
        session_id = event.get("session_id")
        if isinstance(session_id, str) and session_id:
            self.session_id = session_id
        model = event.get("model")
        if isinstance(model, str):
            self.model = model
        agents = event.get("agents")
        self.init_agents = tuple(a for a in agents if isinstance(a, str)) if isinstance(agents, list) else ()
        skills = event.get("skills")
        skill_count = len(skills) if isinstance(skills, list) else 0
        self._say(
            f"[session] {self.session_id or '?'} model={self.model or '?'} "
            f"skills={skill_count} agents={','.join(self.init_agents) or '-'}"
        )
        missing = [name for name in self.required_agents if name not in self.init_agents]
        if missing:
            self.abort_reason = (
                f"sub-agent definition(s) did not load: {', '.join(missing)} "
                "(expected in .claude/agents/ — see `prepare-workspace`)"
            )
            self._say(f"[error] {self.abort_reason}", err=True)

    def _on_assistant(self, event: dict[str, Any]) -> None:
        label = self._label(event)
        for block in _content_blocks(event.get("message")):
            btype = block.get("type")
            if btype == "text":
                text = str(block.get("text", "")).strip()
                if text:
                    self._say(text, prefix=label)
            elif btype == "tool_use":
                self._on_tool_use(block, label)

    def _on_tool_use(self, block: dict[str, Any], label: str) -> None:
        name = str(block.get("name") or "tool")
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        if name in SUBAGENT_TOOLS:
            agent = tool_input.get("subagent_type")
            tool_use_id = block.get("id")
            if isinstance(agent, str) and agent.strip() and isinstance(tool_use_id, str):
                description = tool_input.get("description")
                description = description if isinstance(description, str) else None
                prompt = tool_input.get("prompt")
                self.dispatches[tool_use_id] = Dispatch(tool_use_id, agent.strip(), description)
                self.recorder.add_dispatch(
                    tool_use_id,
                    agent=agent.strip(),
                    description=description,
                    prompt=prompt if isinstance(prompt, str) else None,
                )
                self._say(f"[dispatch] {agent.strip()} — {description or ''}".rstrip(" —"), prefix=label)
                return
        brief = _brief(tool_input)
        self._say(f"[tool] {name}({brief})" if brief else f"[tool] {name}", prefix=label)

    def _on_user(self, event: dict[str, Any]) -> None:
        for block in _content_blocks(event.get("message")):
            if block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id")
            if isinstance(tool_use_id, str) and tool_use_id in self.dispatches:
                self.results[tool_use_id] = _result_text(block.get("content"))
                agent = self.dispatches[tool_use_id].agent
                status = "failed" if block.get("is_error") else "returned"
                self._say(f"[dispatch] {agent} {status}", prefix=self._label(event))
            elif block.get("is_error"):
                self._say(
                    f"[tool-error] {' '.join(_result_text(block.get('content')).split())[:160]}",
                    prefix=self._label(event),
                )

    def _on_result(self, event: dict[str, Any]) -> None:
        self.saw_result = True
        self.result_subtype = event.get("subtype") if isinstance(event.get("subtype"), str) else None
        self.is_error = bool(event.get("is_error")) or (
            self.result_subtype not in (None, "success")
        )
        session_id = event.get("session_id")
        if isinstance(session_id, str) and session_id:
            self.session_id = session_id
        text = event.get("result")
        self.final_text = text if isinstance(text, str) else ""
        turns = event.get("num_turns")
        cost = event.get("total_cost_usd")
        detail = f"turns={turns}" if turns is not None else ""
        if isinstance(cost, (int, float)):
            detail += f" cost=${cost:.4f}"
        detail += _token_detail(event.get("modelUsage"))
        state = "error" if self.is_error else "ok"
        self._say(f"[result] {state} {self.result_subtype or ''} {detail}".rstrip(), err=self.is_error)
