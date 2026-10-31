import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_complete_lines(path, offset):
    if not path.is_file():
        return [], offset
    rows = []
    with path.open("rb") as handle:
        handle.seek(offset)
        while True:
            line = handle.readline()
            if not line or not line.endswith(b"\n"):
                break
            offset = handle.tell()
            try:
                rows.append(json.loads(line.decode("utf-8-sig")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
    return rows, offset


def summarize_event(event):
    operation = event.get("operation", "")
    summary = {
        "time": event.get("receivedAt") or event.get("time"),
        "operation": operation,
    }
    if operation == "command_message":
        summary["rawMessage"] = event.get("rawMessage", "")
    elif operation == "callback":
        summary["callbackName"] = event.get("callbackName", "")
        summary["message"] = str(event.get("message", ""))[:12000]
        summary["stack"] = event.get("stack", [])[:8]
    elif operation in {"live2d_preload_start", "live2d_contains_group"}:
        summary.update({
            "controller": event.get("controller"),
            "commandQueueDictionary": event.get("commandQueueDictionary"),
            "groupId": event.get("groupId"),
        })
    elif operation in {"live2d_release", "live2d_destroy"}:
        summary.update({
            "controller": event.get("controller"),
            "commandQueueDictionary": event.get("commandQueueDictionary"),
        })
    elif operation == "http_audit":
        summary.update({
            "method": event.get("method"),
            "url": event.get("url"),
            "status": event.get("status"),
            "requestBody": str(event.get("requestBody", ""))[:8000],
        })
    elif operation == "request":
        summary.update({
            "method": event.get("method"),
            "url": event.get("url"),
        })
    elif operation == "not_found_command":
        summary["commandName"] = event.get("commandName")
    return summary


def write_actions(path, actions):
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "actions": actions,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--click-events", type=Path, required=True)
    parser.add_argument("--engine-events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window-seconds", type=float, default=8.0)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    actions_path = args.output / "official-click-load-orders.json"
    timeline_path = args.output / "official-click-load-timeline.jsonl"
    status_path = args.output / "correlator-status.txt"
    stop_path = args.output / "STOP"

    click_offset = args.click_events.stat().st_size if args.click_events.is_file() else 0
    engine_offset = args.engine_events.stat().st_size if args.engine_events.is_file() else 0
    actions = []
    next_action_id = 0
    click_times = {}

    while not stop_path.exists():
        click_rows, click_offset = read_complete_lines(
            args.click_events, click_offset)
        for row in click_rows:
            if row.get("client") != "official":
                continue
            clicked_at = parse_time(row.get("time"))
            if clicked_at is None:
                continue
            if row.get("kind") == "mouse_down":
                next_action_id += 1
                action = {
                    "id": next_action_id,
                    "mouseDownTime": clicked_at.isoformat(),
                    "clientX": row.get("client_x"),
                    "clientY": row.get("client_y"),
                    "windowWidth": row.get("window_width"),
                    "windowHeight": row.get("window_height"),
                    "events": [],
                }
                actions.append(action)
                click_times[next_action_id] = clicked_at
            elif row.get("kind") == "mouse_up" and actions:
                actions[-1]["mouseUpTime"] = clicked_at.isoformat()
                actions[-1]["mouseDurationMs"] = int(
                    (clicked_at - click_times[actions[-1]["id"]]).total_seconds()
                    * 1000)
            with timeline_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "type": "click",
                    **row,
                }, ensure_ascii=False) + "\n")

        engine_rows, engine_offset = read_complete_lines(
            args.engine_events, engine_offset)
        for row in engine_rows:
            if row.get("source") != "official":
                continue
            received_at = parse_time(row.get("receivedAt"))
            summary = summarize_event(row)
            matched = []
            if received_at is not None:
                for action in actions:
                    start = click_times[action["id"]]
                    delta = (received_at - start).total_seconds()
                    if -0.2 <= delta <= args.window_seconds:
                        item = dict(summary)
                        item["deltaMs"] = int(delta * 1000)
                        action["events"].append(item)
                        matched.append(action["id"])
            if matched:
                with timeline_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "type": "engine",
                        "actionIds": matched,
                        **summary,
                    }, ensure_ascii=False) + "\n")
                write_actions(actions_path, actions)

        status_path.write_text(
            "running PID=%d actions=%d\n" % (__import__("os").getpid(), len(actions)),
            encoding="ascii",
        )
        time.sleep(0.1)

    write_actions(actions_path, actions)
    status_path.write_text("stopped\n", encoding="ascii")


if __name__ == "__main__":
    main()
