"""The MCP surface, through an in-memory client."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import call, last_sent, list_tools

SNAPSHOT = json.loads((Path(__file__).parent / "tool_schema.json").read_text())


def _without_titles(node: object) -> object:
    """The SDK adds pydantic's generated `title` keys; fastmcp pruned them. They carry no contract."""
    if isinstance(node, dict):
        return {k: _without_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_without_titles(v) for v in node]
    return node


def test_tool_names_and_schema_match_the_snapshot(server) -> None:
    tools = list_tools()

    assert {t.name for t in tools} == set(SNAPSHOT)
    for tool in tools:
        assert _without_titles(tool.inputSchema["properties"]) == SNAPSHOT[tool.name]["properties"], tool.name
        assert sorted(tool.inputSchema["required"]) == sorted(SNAPSHOT[tool.name]["required"]), tool.name


def test_create_returns_text_and_structured_result(server, fake_smtp) -> None:
    result = call(
        "create_proton_calendar_event",
        summary="Lunch",
        start_time="2026-03-10T12:00:00Z",
        end_time="2026-03-10T13:00:00Z",
    )

    assert result.isError is False
    assert result.content[0].text.startswith("Event created successfully.\nUID: ")
    assert result.structuredContent == {"result": result.content[0].text}
    sent = last_sent(fake_smtp)
    assert sent.recipients == ["me@example.com"]
    assert sent.message["Subject"] == "Calendar: Lunch"


def test_bad_arguments_are_a_tool_error_and_send_nothing(server, fake_smtp) -> None:
    result = call("create_proton_calendar_event", summary="x", start_time="not a date", end_time="nor this")

    assert result.isError is True
    assert fake_smtp.instances == []


def test_smtp_failure_is_a_tool_error(server, monkeypatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr("smtplib.SMTP", refuse)
    result = call("cancel_proton_calendar_event", event_uid="u", summary="x")

    assert result.isError is True
    assert "connection refused" in result.content[0].text


def test_server_answers_over_stdio() -> None:
    """The real entry point, with a client on its stdin and stdout."""
    env = {**os.environ, "PROTON_CALENDAR_EMAIL": "me@example.com"}
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    process = subprocess.run(
        [sys.executable, "-c", "from mcp_proton_calendar.app import main; main()"],
        input="".join(json.dumps(r) + "\n" for r in requests),
        capture_output=True, text=True, env=env, timeout=30,
    )
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert replies[0]["result"]["serverInfo"]["name"] == "proton-calendar"
    assert {t["name"] for t in replies[1]["result"]["tools"]} == set(SNAPSHOT)


def test_empty_email_stops_the_server_at_start() -> None:
    for value in ("", "   "):
        env = {**os.environ, "PROTON_CALENDAR_EMAIL": value}
        process = subprocess.run(
            [sys.executable, "-c", "from mcp_proton_calendar.app import main; main()"],
            input="", capture_output=True, text=True, env=env, timeout=30,
        )
        assert process.returncode != 0
        assert "PROTON_CALENDAR_EMAIL" in process.stderr
