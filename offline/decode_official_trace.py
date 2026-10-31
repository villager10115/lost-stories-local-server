#!/usr/bin/env python3
"""Decode official-client command logs and captured API bodies.

The output remains private: raw command payloads can contain account state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


TRACE_RE = re.compile(
    r"^\[OfficialTrace\]\|(?P<time>[^|]*)\|(?P<kind>[^|]*)\|(?P<body>.*)$"
)
CALLBACK_FULL_LIMIT = 256 * 1024
COMMAND_RE = re.compile(
    r"^(?P<scheme>[^:]+)://(?P<command>[^?]+)"
    r"(?:\?commandParam=(?P<param>.*))?$",
    re.DOTALL,
)


def decode_command(raw_message: str) -> dict[str, Any]:
    decoded_raw = unquote(raw_message)
    match = COMMAND_RE.match(decoded_raw)
    if not match:
        return {
            "scheme": "",
            "command": "",
            "param_kind": "unparsed",
            "param": decoded_raw,
        }

    param_text = match.group("param")
    if not param_text:
        return {
            "scheme": match.group("scheme"),
            "command": match.group("command"),
            "param_kind": "empty",
            "param": None,
        }

    try:
        param = json.loads(param_text)
        kind = "json"
    except json.JSONDecodeError:
        param = param_text
        kind = "text"

    return {
        "scheme": match.group("scheme"),
        "command": match.group("command"),
        "param_kind": kind,
        "param": param,
    }


def parse_player_log(lines: Iterable[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        match = TRACE_RE.match(line.rstrip("\r\n"))
        if not match:
            continue
        kind = match.group("kind").strip()
        body = match.group("body")
        event: dict[str, Any] = {
            "line": line_number,
            "time": match.group("time").strip(),
            "kind": kind,
        }
        if kind == "command":
            command_id, separator, raw_message = body.partition("|")
            event["command_id"] = command_id.strip()
            event["raw_message_length"] = len(raw_message) if separator else 0
            if separator:
                event.update(decode_command(raw_message))
        elif kind == "callback":
            callback, separator, message = body.partition("|")
            event["callback"] = callback
            event["message_length"] = len(message) if separator else 0
            if separator:
                if len(message) <= CALLBACK_FULL_LIMIT:
                    try:
                        event["message_json"] = json.loads(message)
                    except json.JSONDecodeError:
                        event["message_text"] = message
                else:
                    raw_message = message.encode("utf-8")
                    event["message_skipped"] = "too_large"
                    event["message_sha256"] = hashlib.sha256(
                        raw_message
                    ).hexdigest()
                    event["message_bytes"] = len(raw_message)
                    event["message_prefix"] = message[:256]
        elif kind == "request":
            url, separator, method = body.partition("|")
            event["url"] = url
            event["method"] = method if separator else ""
        else:
            event["body"] = body
        events.append(event)
    return events


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def decode_api_bodies(capture_dir: Path) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for event in read_jsonl(capture_dir / "events.jsonl"):
        if event.get("kind") not in {"response_body", "request_body"}:
            continue
        relative = event.get("file")
        if not isinstance(relative, str):
            continue
        body_path = capture_dir / relative
        if not body_path.exists():
            continue
        raw = body_path.read_bytes()
        record = {
            key: event.get(key)
            for key in (
                "time",
                "kind",
                "request_id",
                "path",
                "bytes",
                "sha256",
                "file",
            )
        }
        try:
            record["json"] = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            record["text_prefix"] = raw[:1000].decode("utf-8", errors="replace")
        decoded.append(record)
    return decoded


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--player-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    with args.player_log.open("r", encoding="utf-8", errors="replace") as stream:
        operations = parse_player_log(stream)
    write_jsonl(args.output / "operations.jsonl", operations)
    write_jsonl(
        args.output / "api_bodies.jsonl",
        decode_api_bodies(args.capture),
    )
    summary = {
        "capture": str(args.capture.resolve()),
        "player_log": str(args.player_log.resolve()),
        "operation_events": len(operations),
        "commands": sum(item["kind"] == "command" for item in operations),
        "callbacks": sum(item["kind"] == "callback" for item in operations),
        "native_requests": sum(item["kind"] == "request" for item in operations),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
