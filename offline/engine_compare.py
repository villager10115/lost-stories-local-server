import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_json_lines(path):
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def parse_time(value):
    if not value:
        return None
    try:
        value = re.sub(r"(\.\d{6})\d+(?=Z|[+-]\d\d:\d\d)", r"\1", value)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def engine_event_time(event):
    value = event.get("timestamp")
    if isinstance(value, (int, float)):
        return value / 1000
    return parse_time(event.get("receivedAt"))


def clicks(events):
    result = []
    starts = {}
    sequence = 0
    for event in events:
        if event.get("kind") == "click_down":
            starts[event.get("client")] = event
        elif event.get("kind") == "click":
            start = starts.get(event.get("id"), {})
            sequence += 1
            result.append({
                "id": event.get("id", sequence),
                "client": event.get("client"),
                "time": event.get("time"),
                "epoch": parse_time(event.get("time")),
                "client_x": event.get("client_x"),
                "client_y": event.get("client_y"),
                "down_client_x": start.get("client_x"),
                "down_client_y": start.get("client_y"),
                "durationMs": event.get("duration_ms"),
                "moved": event.get("moved"),
            })
        elif event.get("kind") == "mouse_down":
            starts[f"{event.get('client')}:{event.get('pid')}"] = event
        elif event.get("kind") == "mouse_up":
            start = starts.get(f"{event.get('client')}:{event.get('pid')}", {})
            sequence += 1
            result.append({
                "id": sequence,
                "client": event.get("client"),
                "time": event.get("time"),
                "epoch": parse_time(event.get("time")),
                "client_x": event.get("client_x"),
                "client_y": event.get("client_y"),
                "down_client_x": start.get("client_x"),
                "down_client_y": start.get("client_y"),
                "durationMs": (
                    event.get("timestamp") - start.get("timestamp")
                    if event.get("timestamp") is not None
                    and start.get("timestamp") is not None else None
                ),
                "moved": None,
            })
    return result


def operation_view(index, event):
    operation = event.get("operation")
    item = {
        "index": index,
        "source": event.get("source"),
        "operation": operation,
        "elapsedMs": event.get("elapsedMs"),
    }
    if operation == "command":
        item["path"] = event.get("path")
        item["rawMessage"] = event.get("rawMessage")
    elif operation == "command_message":
        item["rawMessage"] = event.get("rawMessage")
    elif operation == "callback":
        item["callbackName"] = event.get("callbackName")
        message = event.get("message")
        item["message"] = message
        try:
            parsed = json.loads(message or "{}")
            if isinstance(parsed, dict) and parsed.get("serif"):
                item["serif"] = parsed["serif"]
        except (json.JSONDecodeError, TypeError):
            pass
    elif operation == "request":
        item["method"] = event.get("method")
        item["url"] = event.get("url")
    elif operation == "dom_snapshot":
        item["route"] = event.get("hash") or event.get("href")
        item["title"] = event.get("title")
        item["headings"] = (event.get("headings") or [])[:20]
        item["buttons"] = (event.get("buttons") or [])[:30]
        item["dialogs"] = (event.get("dialogs") or [])[:10]
        item["text"] = (event.get("text") or "")[:800]
    elif operation == "http_audit":
        item["method"] = event.get("method")
        item["url"] = event.get("url")
        item["status"] = event.get("status")
        item["requestBody"] = (event.get("requestBody") or "")[:3000]
        item["responseBody"] = (event.get("responseBody") or "")[:4000]
    else:
        for key in ("hook", "error"):
            if event.get(key):
                item[key] = event[key]
    return item


def operation_clusters(engine_events, client, gap_seconds=1.5):
    selected = []
    for index, event in enumerate(engine_events, start=1):
        if event.get("source") != client:
            continue
        if event.get("operation") not in {
                "command", "command_message", "callback", "request",
                "dom_snapshot", "http_audit", "hook_error"}:
            continue
        epoch = engine_event_time(event)
        if epoch is None:
            continue
        selected.append((epoch, operation_view(index, event)))
    selected.sort(key=lambda item: item[0])
    clusters = []
    current = None
    for epoch, event in selected:
        if current is None or epoch - current["endEpoch"] > gap_seconds:
            current = {
                "startEpoch": epoch,
                "endEpoch": epoch,
                "operations": [],
            }
            clusters.append(current)
        current["endEpoch"] = epoch
        item = dict(event)
        item["offsetMs"] = round((epoch - current["startEpoch"]) * 1000)
        current["operations"].append(item)
    for cluster in clusters:
        cluster["startedAt"] = datetime.fromtimestamp(
            cluster["startEpoch"], timezone.utc).isoformat()
        cluster.pop("startEpoch", None)
        cluster.pop("endEpoch", None)
    return clusters


def network_endpoints(output, client):
    events = read_json_lines(output / "network-events.jsonl")
    endpoints = {}
    dns = {}
    for event in events:
        if event.get("kind") == "dns" and event.get("data"):
            dns.setdefault(event["data"], set()).add(event.get("name"))
        if (event.get("kind") == "tcp" and event.get("client") == client
                and event.get("remote_address")
                and not event["remote_address"].startswith(("127.", "::"))
                and event.get("remote_port")):
            key = f"{event['remote_address']}:{event['remote_port']}"
            endpoints[key] = endpoints.get(key, 0) + 1
    return [
        {
            "endpoint": endpoint,
            "connections": count,
            "dns": sorted(dns.get(endpoint.rsplit(":", 1)[0], [])),
        }
        for endpoint, count in sorted(endpoints.items())
    ]


def build_report(output):
    click_events = read_json_lines(output / "click-events.jsonl")
    engine_events = read_json_lines(output / "engine-events.jsonl")
    actions = clicks(click_events)
    for action in actions:
        if action["epoch"] is None:
            action["operations"] = []
            continue
        operations = []
        for index, event in enumerate(engine_events, start=1):
            if event.get("source") != action["client"]:
                continue
            event_time = engine_event_time(event)
            if event_time is None:
                continue
            if action["epoch"] - 0.15 <= event_time <= action["epoch"] + 4.0:
                view = operation_view(index, event)
                view["offsetMs"] = round((event_time - action["epoch"]) * 1000)
                operations.append(view)
        action["operations"] = operations

    report = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "clickCount": len(actions),
        "engineEventCount": len(engine_events),
        "clusters": {
            client: operation_clusters(engine_events, client)
            for client in ("official", "packaged-local")
        },
        "network": {
            client: network_endpoints(output, client)
            for client in ("official", "packaged-local")
        },
        "actions": actions,
    }
    (output / "engine-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Engine operation comparison",
        "",
        f"Updated: {report['updatedAt']}",
        "",
        "Passive trace only. Screenshots are not read or analyzed.",
        "",
        f"Clicks: {len(actions)}; engine events: {len(engine_events)}",
        "",
    ]
    for client, label in (
            ("official", "Official"), ("packaged-local", "Packaged local")):
        lines.append(f"## {label} network")
        lines.append("")
        for endpoint in report["network"][client]:
            names = ", ".join(endpoint["dns"]) or "unresolved"
            lines.append(
                f"- {endpoint['endpoint']} connections={endpoint['connections']} "
                f"domains={names}")
        if not report["network"][client]:
            lines.append("- No remote endpoint observed.")
        lines.append("")
        lines.append(f"## {label} engine clusters")
        lines.append("")
        for cluster in report["clusters"][client]:
            lines.append(f"### {cluster['startedAt']}")
            lines.append("")
            for operation in cluster["operations"]:
                if operation["operation"] == "command":
                    detail = (
                        f"path={operation.get('path')} "
                        f"raw={operation.get('rawMessage')}")
                elif operation["operation"] == "command_message":
                    detail = f"raw={operation.get('rawMessage')}"
                elif operation["operation"] == "callback":
                    detail = (
                        f"callback={operation.get('callbackName')} "
                        f"message={operation.get('message')}")
                elif operation["operation"] == "request":
                    detail = f"{operation.get('method')} {operation.get('url')}"
                elif operation["operation"] == "dom_snapshot":
                    detail = (
                        f"route={operation.get('route')} "
                        f"title={operation.get('title')} "
                        f"headings={operation.get('headings')} "
                        f"dialogs={operation.get('dialogs')}")
                elif operation["operation"] == "http_audit":
                    detail = (
                        f"{operation.get('method')} {operation.get('url')} "
                        f"status={operation.get('status')} "
                        f"request={operation.get('requestBody')} "
                        f"response={operation.get('responseBody')}")
                else:
                    detail = operation.get("error")
                lines.append(
                    f"- +{operation.get('offsetMs', 0)}ms "
                    f"{operation['operation']}: {detail}")
            lines.append("")
        if not report["clusters"][client]:
            lines.append("No engine operation observed.")
            lines.append("")
    lines.append("## Click-associated actions")
    lines.append("")
    for action in actions:
        lines.append(
            f"## {action['time']} {action['client']} click {action['id']}")
        lines.append("")
        lines.append(
            f"- Coordinates: {action['down_client_x']},{action['down_client_y']} -> "
            f"{action['client_x']},{action['client_y']}; duration={action['durationMs']}ms")
        lines.append(f"- Engine operations: {len(action['operations'])}")
        for operation in action["operations"]:
            if operation["operation"] == "command":
                detail = f"path={operation.get('path')} raw={operation.get('rawMessage')}"
            elif operation["operation"] == "command_message":
                detail = f"raw={operation.get('rawMessage')}"
            elif operation["operation"] == "callback":
                detail = (
                    f"callback={operation.get('callbackName')} "
                    f"message={operation.get('message')}")
            elif operation["operation"] == "request":
                detail = f"{operation.get('method')} {operation.get('url')}"
            elif operation["operation"] == "dom_snapshot":
                detail = (
                    f"route={operation.get('route')} "
                    f"title={operation.get('title')} "
                    f"headings={operation.get('headings')} "
                    f"dialogs={operation.get('dialogs')}")
            elif operation["operation"] == "http_audit":
                detail = (
                    f"{operation.get('method')} {operation.get('url')} "
                    f"status={operation.get('status')} "
                    f"request={operation.get('requestBody')} "
                    f"response={operation.get('responseBody')}")
            else:
                detail = json.dumps(operation, ensure_ascii=False)
            lines.append(
                f"  - +{operation.get('offsetMs', 0)}ms "
                f"{operation['operation']}: {detail}")
        if not action["operations"]:
            lines.append("  - No engine event observed in the click window.")
        lines.append("")
    (output / "ENGINE_COMPARISON.md").write_text(
        "\n".join(lines), encoding="utf-8")
    for client, directory, label in (
            ("official", "official", "Official"),
            ("packaged-local", "local", "Packaged local")):
        client_lines = [
            f"# {label} engine trace",
            "",
            f"Updated: {report['updatedAt']}",
            "",
            "Passive Mono hooks only. No screenshots or injected input.",
            "",
            "## Network",
            "",
        ]
        for endpoint in report["network"][client]:
            names = ", ".join(endpoint["dns"]) or "unresolved"
            client_lines.append(
                f"- {endpoint['endpoint']} connections={endpoint['connections']} "
                f"domains={names}")
        if not report["network"][client]:
            client_lines.append("- No remote endpoint observed.")
        client_lines.extend(["", "## Engine clusters", ""])
        for cluster in report["clusters"][client]:
            client_lines.extend([f"### {cluster['startedAt']}", ""])
            for operation in cluster["operations"]:
                if operation["operation"] == "command":
                    detail = (
                        f"path={operation.get('path')} "
                        f"raw={operation.get('rawMessage')}")
                elif operation["operation"] == "command_message":
                    detail = f"raw={operation.get('rawMessage')}"
                elif operation["operation"] == "callback":
                    detail = (
                        f"callback={operation.get('callbackName')} "
                        f"serif={operation.get('serif') or ''} "
                        f"message={operation.get('message')}")
                elif operation["operation"] == "request":
                    detail = f"{operation.get('method')} {operation.get('url')}"
                elif operation["operation"] == "dom_snapshot":
                    detail = (
                        f"route={operation.get('route')} "
                        f"title={operation.get('title')} "
                        f"headings={operation.get('headings')} "
                        f"dialogs={operation.get('dialogs')}")
                elif operation["operation"] == "http_audit":
                    detail = (
                        f"{operation.get('method')} {operation.get('url')} "
                        f"status={operation.get('status')} "
                        f"request={operation.get('requestBody')} "
                        f"response={operation.get('responseBody')}")
                else:
                    detail = operation.get("error")
                client_lines.append(
                    f"- +{operation.get('offsetMs', 0)}ms "
                    f"{operation['operation']}: {detail}")
            client_lines.append("")
        client_directory = output / directory
        client_directory.mkdir(parents=True, exist_ok=True)
        (client_directory / "ENGINE_REPORT.md").write_text(
            "\n".join(client_lines), encoding="utf-8")
    return report


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python engine_compare.py OUTPUT_DIRECTORY")
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    build_report(root)
    print(root / "ENGINE_COMPARISON.md")


if __name__ == "__main__":
    main()
