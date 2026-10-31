import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


COMMAND_LABELS = {
    "PLAY_SE": "play UI sound",
    "LOAD_LIVE2D": "load Live2D character",
    "EXECUTE_LIVE2D": "execute Live2D animation",
    "TRANSFORM_LIVE2D": "position Live2D",
    "RELEASE_LIVE2D": "release Live2D",
    "LOAD_PILOT_BG": "load pilot background",
    "RELEASE_PILOT_BG": "release pilot background",
    "GET_BASE64": "request native image data",
    "RELEASE_BASE64": "release native image data",
    "PLAY_BGM": "change BGM",
    "TOGGLE_ACTIVE_POST_PROCESSING_VOLUME": "change post-processing",
    "INACTIVATE_ALL_POST_PROCESSING_VOLUME": "disable post-processing",
    "FADE_IN_3D_BG": "fade in 3D background",
    "SET_WEBVIEW_VISIBLE": "show/hide WebView",
    "REMOVE_NOTIFICATION": "remove local notification",
}


def read_json_lines(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_command(raw):
    if not raw or not raw.startswith("zero://"):
        return None
    parsed = urlsplit(raw)
    command = parsed.netloc or parsed.path
    value = parse_qs(parsed.query).get("commandParam", [""])[0]
    if value:
        value = unquote(value)
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    else:
        value = None
    return command, value


def event_time(event):
    value = event.get("timestamp")
    if isinstance(value, (int, float)):
        return value / 1000
    return parse_time(event.get("receivedAt") or event.get("time"))


def timeline_events(engine_events, network_events):
    events = []
    for event in engine_events:
        if event.get("source") != "official":
            continue
        operation = event.get("operation")
        epoch = event_time(event)
        if operation == "command_message":
            parsed = parse_command(event.get("rawMessage"))
            if not parsed:
                continue
            command, parameters = parsed
            events.append({
                "epoch": epoch,
                "time": event.get("receivedAt"),
                "kind": "command",
                "command": command,
                "label": COMMAND_LABELS.get(command, command),
                "parameters": parameters,
            })
        elif operation == "callback":
            message = event.get("message")
            parsed = None
            if message:
                try:
                    parsed = json.loads(message)
                except json.JSONDecodeError:
                    parsed = message
            events.append({
                "epoch": epoch,
                "time": event.get("receivedAt"),
                "kind": "callback",
                "callback": event.get("callbackName"),
                "payload": parsed,
            })
        elif operation == "dom_snapshot":
            events.append({
                "epoch": epoch,
                "time": event.get("receivedAt"),
                "kind": "page",
                "href": event.get("href"),
                "route": event.get("hash"),
                "title": event.get("title"),
                "headings": event.get("headings"),
                "buttons": event.get("buttons"),
                "dialogs": event.get("dialogs"),
                "text": event.get("text"),
            })
        elif operation == "http_audit":
            events.append({
                "epoch": epoch,
                "time": event.get("receivedAt"),
                "kind": "http",
                "method": event.get("method"),
                "url": event.get("url"),
                "status": event.get("status"),
                "requestBody": event.get("requestBody"),
                "responseBody": event.get("responseBody"),
            })
    for event in network_events:
        if event.get("kind") not in {"process", "tcp", "dns"}:
            continue
        kind = event.get("kind")
        if kind == "tcp" and event.get("client") != "official":
            continue
        events.append({
            "epoch": parse_time(event.get("time")),
            "time": event.get("time"),
            "kind": "network_" + kind,
            "payload": event,
        })
    return sorted(events, key=lambda item: item.get("epoch") or 0)


def network_summary(network_events):
    tcp = {}
    dns = {}
    for event in network_events:
        if event.get("kind") == "tcp" and event.get("client") == "official":
            remote = event.get("remote_address")
            port = event.get("remote_port")
            if remote and port and not remote.startswith(("127.", "::")):
                key = f"{remote}:{port}"
                item = tcp.setdefault(key, {
                    "endpoint": key,
                    "pid": event.get("pid"),
                    "process": event.get("process"),
                })
                if event.get("process"):
                    item["process"] = event["process"]
        elif event.get("kind") == "dns" and event.get("data"):
            dns.setdefault(event["data"], set()).add(event.get("name"))
    rows = []
    for endpoint, item in sorted(tcp.items()):
        address = endpoint.rsplit(":", 1)[0]
        rows.append({
            **item,
            "domains": sorted(dns.get(address, [])),
        })
    return rows


def write_markdown(events, network, path):
    lines = [
        "# Official client end-to-end timeline",
        "",
        "This timeline combines engine commands, callbacks, page DOM state, "
        "WebView AJAX, and process-level network metadata.",
        "",
        "## Network mapping",
        "",
        "| Endpoint | Process | PID | DNS names |",
        "|---|---|---:|---|",
    ]
    for item in network:
        lines.append(
            f"| {item['endpoint']} | {item.get('process') or '-'} | "
            f"{item.get('pid') or '-'} | "
            f"{', '.join(item['domains']) or 'unresolved'} |")
    lines.extend(["", "## Page sequence", ""])
    for event in events:
        if event["kind"] != "page":
            continue
        text = (event.get("text") or "").replace("\n", " ")[:800]
        lines.extend([
            f"### {event['time']} `{event['route']}`",
            "",
            f"- Buttons: {' | '.join(event.get('buttons') or []) or '-'}",
            f"- Dialogs: {' | '.join(event.get('dialogs') or []) or '-'}",
            "",
            text,
            "",
        ])
    lines.extend(["## HTTP order", ""])
    index = 0
    for event in events:
        if event["kind"] != "http":
            continue
        index += 1
        lines.extend([
            f"{index}. {event['time']} `{event['method']} {event['url']}` "
            f"status={event['status']}",
        ])
        if event.get("requestBody"):
            lines.append(f"   Request: `{event['requestBody'][:2000]}`")
        response = event.get("responseBody") or ""
        lines.append(f"   Response bytes in audit: {len(response)}")
    lines.extend(["", "## Command and callback order", ""])
    sound_counts = Counter()
    for event in events:
        if event["kind"] == "command":
            if event["command"] == "PLAY_SE":
                cue = (
                    event.get("parameters", {}).get("cueName")
                    if isinstance(event.get("parameters"), dict) else None)
                sound_counts[cue or "unknown"] += 1
                continue
            parameters = json.dumps(
                event.get("parameters"), ensure_ascii=False)
            lines.append(
                f"- {event['time']} COMMAND `{event['command']}` "
                f"({event['label']}) `{parameters}`")
        elif event["kind"] == "callback":
            payload = event.get("payload")
            if isinstance(payload, dict) and payload.get("serif"):
                lines.append(
                    f"- {event['time']} CALLBACK `{event['callback']}` "
                    f"serif={payload['serif']!r}")
            elif payload:
                compact = json.dumps(payload, ensure_ascii=False)
                lines.append(
                    f"- {event['time']} CALLBACK `{event['callback']}` "
                    f"`{compact[:800]}`")
    lines.extend(["", "## Collapsed UI sound counts", ""])
    for cue, count in sorted(sound_counts.items()):
        lines.append(f"- `{cue}`: {count}")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_directory")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.capture_directory).resolve()
    engine_events = read_json_lines(root / "engine-events.jsonl")
    network_events = read_json_lines(root / "network-events.jsonl")
    events = timeline_events(engine_events, network_events)
    network = network_summary(network_events)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "coverage": (
            "Official engine trace starts when the live hook attaches; "
            "network samples start when the monitor starts."
        ),
        "network": network,
        "events": events,
    }
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = output.with_suffix(".md")
    write_markdown(events, network, markdown)
    print(json.dumps({
        "output": str(output),
        "markdown": str(markdown),
        "events": len(events),
        "pages": sum(1 for item in events if item["kind"] == "page"),
        "http": sum(1 for item in events if item["kind"] == "http"),
        "commands": sum(1 for item in events if item["kind"] == "command"),
        "callbacks": sum(1 for item in events if item["kind"] == "callback"),
        "networkEndpoints": len(network),
    }, indent=2))


if __name__ == "__main__":
    main()
