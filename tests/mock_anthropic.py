"""A scripted Anthropic Messages endpoint for testing harness plumbing offline.

It streams SSE like the real API and answers from a script, not a model, so a test can prove
the plumbing (sub-agent spawn, parallelism, preload, tool allowlists, headers, stream parsing)
without credentials. It proves nothing about agent quality: that is what live runs are for.

Script, by the request's system prompt:

- contains ``MOCK-SUPERVISOR``: first turn spawns ``Agent`` twice in one message (subagent
  type from ``MOCK-AGENT=<name>`` in the system prompt); after the results, replies
  ``SUPERVISED: <results>``;
- anything else (a sub-agent): replies ``SMOKE_OK``, plus `` PRELOAD`` when a preloaded skill
  block is in its system prompt, after ``child_delay`` seconds.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _system_text(body: dict[str, Any]) -> str:
    system = body.get("system")
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    return ""


def _tool_results(body: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for message in body.get("messages", []):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    out.append(" ".join(b.get("text", "") for b in inner if isinstance(b, dict)))
                elif isinstance(inner, str):
                    out.append(inner)
    return out


class MockAnthropic:
    def __init__(self, child_delay: float = 0.0) -> None:
        self.child_delay = child_delay
        self.requests: list[dict[str, Any]] = []
        self.in_flight = 0
        self.max_in_flight_children = 0
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "MockAnthropic":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()

    # ------------------------------------------------------------------ script

    def reply(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        system = _system_text(body)
        if "MOCK-SUPERVISOR" in system:
            results = _tool_results(body)
            if results:
                return [{"type": "text", "text": "SUPERVISED: " + " | ".join(results)}]
            match = re.search(r"MOCK-AGENT=([\w-]+)", system)
            agent = match.group(1) if match else "smoke"
            return [
                {"type": "tool_use", "id": f"toolu_{i}", "name": "Agent",
                 "input": {"subagent_type": agent, "description": f"child-{i}", "prompt": f"Task {i}: reply."}}
                for i in (1, 2)
            ]
        preload = "<skill name=" in system
        return [{"type": "text", "text": "SMOKE_OK" + (" PRELOAD" if preload else "")}]

    # ------------------------------------------------------------------- server

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:  # quiet
                pass

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                is_child = "MOCK-SUPERVISOR" not in _system_text(body)
                with mock._lock:
                    mock.requests.append({
                        "path": self.path,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "system": _system_text(body),
                        "tools": [t.get("name") for t in body.get("tools", []) if isinstance(t, dict)],
                        "model": body.get("model"),
                        "thinking": body.get("thinking"),
                        "child": is_child,
                    })
                    if is_child:
                        mock.in_flight += 1
                        mock.max_in_flight_children = max(mock.max_in_flight_children, mock.in_flight)
                try:
                    if is_child and mock.child_delay:
                        time.sleep(mock.child_delay)
                    self._stream(body, mock.reply(body))
                finally:
                    if is_child:
                        with mock._lock:
                            mock.in_flight -= 1

            def _send(self, event: str, data: dict[str, Any]) -> None:
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())

            def _stream(self, body: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.end_headers()
                model = body.get("model", "mock")
                self._send("message_start", {"type": "message_start", "message": {
                    "id": "msg_mock", "type": "message", "role": "assistant", "model": model,
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 100, "output_tokens": 1,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}})
                stop = "end_turn"
                for index, block in enumerate(blocks):
                    if block["type"] == "text":
                        self._send("content_block_start", {"type": "content_block_start", "index": index,
                                                           "content_block": {"type": "text", "text": ""}})
                        self._send("content_block_delta", {"type": "content_block_delta", "index": index,
                                                           "delta": {"type": "text_delta", "text": block["text"]}})
                    else:
                        stop = "tool_use"
                        self._send("content_block_start", {"type": "content_block_start", "index": index,
                                                           "content_block": {"type": "tool_use", "id": block["id"],
                                                                             "name": block["name"], "input": {}}})
                        self._send("content_block_delta", {"type": "content_block_delta", "index": index,
                                                           "delta": {"type": "input_json_delta",
                                                                     "partial_json": json.dumps(block["input"])}})
                    self._send("content_block_stop", {"type": "content_block_stop", "index": index})
                self._send("message_delta", {"type": "message_delta",
                                             "delta": {"stop_reason": stop, "stop_sequence": None},
                                             "usage": {"output_tokens": 10}})
                self._send("message_stop", {"type": "message_stop"})
                self.wfile.flush()

        return Handler
