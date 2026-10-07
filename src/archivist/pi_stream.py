"""Read ``pi --mode json`` for one headless session (ADR 0008).

The same surface as ``StreamMonitor`` (the run loop, the dispatch check and the transcripts
depend on nothing else), from Pi's events instead of Claude Code's:

- ``session`` → session id;
- the first ``message_end`` (role ``system``) lists the session's tools (``toolsAdded``): when the run needs
  sub-agents and ``Agent`` is not among them, the engine extension did not load and the
  session is aborted before it spends tokens (Claude Code's ``init`` check, for Pi);
- ``tool_execution_start`` / ``_end`` of ``Agent`` → a dispatch and its result text; the
  extension reports the sub-agent's usage in the result's ``details``, so the cost line
  covers the whole session as Claude Code's does;
- assistant ``message_end`` → text, turns, usage, and ``stopReason`` (Pi's JSON mode exits 0
  on a failed response: ``error`` or ``aborted`` is the failure signal);
- ``agent_end`` → the result.

Sub-agents run as separate processes; the extension writes each one's events to
``<events_dir>/<tool call id>.jsonl`` and the transcripts read them from there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archivist.stream import SUBAGENT_TOOLS, Dispatch, StreamMonitor, _brief

_FAILED_STOPS = frozenset({"error", "aborted"})


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    return ""


def _result_text(result: Any) -> str:
    if isinstance(result, dict):
        return _text(result.get("content"))
    return _text(result)


def _tools_from_system(message: dict[str, Any]) -> tuple[str, ...] | None:
    """The session's tools: Pi records them as ``toolsAdded`` on the first system message."""
    added = message.get("toolsAdded")
    if not isinstance(added, list):
        return None
    return tuple(t["name"] for t in added if isinstance(t, dict) and isinstance(t.get("name"), str))


@dataclass(slots=True)
class PiStreamMonitor(StreamMonitor):
    events_dir: Path | None = None
    turns: int = 0
    cost: float = 0.0
    tokens: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0})
    stop_reason: str | None = None
    error_message: str | None = None
    session_tools: tuple[str, ...] = ()

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
        if kind == "session":
            self._on_session(event)
        elif kind == "message_end":
            self._on_message_end(event.get("message"))
        elif kind == "tool_execution_start":
            self._on_tool_start(event)
        elif kind == "tool_execution_end":
            self._on_tool_end(event)
        elif kind == "agent_end" and not event.get("willRetry"):
            self._on_agent_end()

    def write_transcripts(self, workspace: Path) -> list[Path]:
        if self.events_dir is not None:
            for tool_use_id in self.dispatches:
                path = self.events_dir / f"{tool_use_id}.jsonl"
                if not path.is_file():
                    continue
                for raw in path.read_text(encoding="utf-8").splitlines():
                    try:
                        child = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(child, dict):
                        child["parent_tool_use_id"] = tool_use_id
                        self.recorder.add_event(child)
        return StreamMonitor.write_transcripts(self, workspace)

    # -- events ------------------------------------------------------------------

    def _on_session(self, event: dict[str, Any]) -> None:
        session_id = event.get("id")
        if isinstance(session_id, str) and session_id:
            self.session_id = session_id

    def _on_message_end(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        role = message.get("role")
        if role == "system":
            tools = _tools_from_system(message)
            if tools is None or self.session_tools:
                return
            self.session_tools = tools
            self.init_agents = tuple(self.required_agents) if "Agent" in tools else ()
            self._say(f"[session] {self.session_id or '?'} harness=pi tools={','.join(tools)}")
            if self.required_agents and "Agent" not in tools:
                self.abort_reason = (
                    "the archivist Pi extension did not load: the session has no `Agent` tool "
                    "(expected in .claude/pi/extensions/ — see `prepare-workspace`)"
                )
                self._say(f"[error] {self.abort_reason}", err=True)
            return
        if role != "assistant":
            return
        self.turns += 1
        if isinstance(message.get("model"), str):
            self.model = message["model"]
        usage = message.get("usage")
        if isinstance(usage, dict):
            for key in self.tokens:
                value = usage.get(key)
                if isinstance(value, (int, float)):
                    self.tokens[key] += int(value)
            cost = usage.get("cost")
            if isinstance(cost, dict) and isinstance(cost.get("total"), (int, float)):
                self.cost += float(cost["total"])
        stop = message.get("stopReason")
        self.stop_reason = stop if isinstance(stop, str) else None
        error = message.get("errorMessage")
        self.error_message = error if isinstance(error, str) else None
        text = _text(message.get("content"))
        if text:
            self.final_text = text
            self._say(text)
        if self.stop_reason in _FAILED_STOPS:
            self._say(f"[error] {self.error_message or self.stop_reason}", err=True)

    def _on_tool_start(self, event: dict[str, Any]) -> None:
        name = str(event.get("toolName") or "tool")
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        tool_use_id = event.get("toolCallId")
        if name in SUBAGENT_TOOLS and isinstance(tool_use_id, str):
            agent = args.get("subagent_type")
            if isinstance(agent, str) and agent.strip():
                description = args.get("description") if isinstance(args.get("description"), str) else None
                prompt = args.get("prompt") if isinstance(args.get("prompt"), str) else None
                self.dispatches[tool_use_id] = Dispatch(tool_use_id, agent.strip(), description)
                self.recorder.add_dispatch(tool_use_id, agent=agent.strip(), description=description, prompt=prompt)
                self._say(f"[dispatch] {agent.strip()} — {description or ''}".rstrip(" —"))
                return
        brief = _brief(args)
        self._say(f"[tool] {name}({brief})" if brief else f"[tool] {name}")

    def _on_tool_end(self, event: dict[str, Any]) -> None:
        tool_use_id = event.get("toolCallId")
        result = event.get("result")
        failed = bool(event.get("isError")) or (isinstance(result, dict) and bool(result.get("isError")))
        if isinstance(tool_use_id, str) and tool_use_id in self.dispatches:
            self.results[tool_use_id] = _result_text(result)
            details = result.get("details") if isinstance(result, dict) else None
            usage = details.get("usage") if isinstance(details, dict) else None
            if isinstance(usage, dict):
                if isinstance(usage.get("cost"), (int, float)):
                    self.cost += float(usage["cost"])
                for key in self.tokens:
                    if isinstance(usage.get(key), (int, float)):
                        self.tokens[key] += int(usage[key])
            agent = self.dispatches[tool_use_id].agent
            self._say(f"[dispatch] {agent} {'failed' if failed else 'returned'}")
        elif failed:
            self._say(f"[tool-error] {' '.join(_result_text(result).split())[:160]}")

    def _on_agent_end(self) -> None:
        self.saw_result = True
        self.is_error = self.stop_reason in _FAILED_STOPS
        self.result_subtype = "success" if not self.is_error else (self.stop_reason or "error")
        detail = (
            f"turns={self.turns} cost=${self.cost:.4f} "
            f"tokens in={self.tokens['input']} out={self.tokens['output']} "
            f"cache_read={self.tokens['cacheRead']} cache_write={self.tokens['cacheWrite']}"
        )
        state = "error" if self.is_error else "ok"
        self._say(f"[result] {state} {self.result_subtype} {detail}", err=self.is_error)
