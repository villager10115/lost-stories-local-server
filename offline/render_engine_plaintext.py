import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def read_json_lines(path):
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def parse_command(raw):
    if not raw or not raw.startswith("zero://"):
        return None
    parsed = urlsplit(raw)
    parameters = parse_qs(parsed.query).get("commandParam", [""])[0]
    if parameters:
        parameters = unquote(parameters)
        try:
            decoded = json.loads(parameters)
        except json.JSONDecodeError:
            decoded = parameters
    else:
        decoded = None
    return {
        "command": parsed.netloc or parsed.path,
        "parameters": decoded,
    }


def load_masterdata(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_inventory(path):
    connection = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        items = {
            row[0]: {"quantity": row[1], "updatedAt": row[2]}
            for row in connection.execute(
                "SELECT item_id, quantity, updated_at FROM user_game_items")
        }
        wallet = connection.execute(
            "SELECT free_sakuradite, paid_sakuradite, gold, skip_tickets, "
            "stamina, max_stamina FROM user_wallets LIMIT 1").fetchone()
    finally:
        connection.close()
    return items, wallet


def build_report(events, masterdata, state_db):
    item_definitions = {
        item["itemId"]: item for item in masterdata.get("itemList", [])
    }
    inventory, wallet = load_inventory(state_db)
    dialogues = []
    commands = []
    issues = []
    snapshots = []
    http_audits = []
    for event in events:
        operation = event.get("operation")
        source = event.get("source")
        received = event.get("receivedAt")
        if operation == "callback":
            message = event.get("message")
            parsed = None
            if message:
                try:
                    parsed = json.loads(message)
                except json.JSONDecodeError:
                    parsed = message
            serif = parsed.get("serif") if isinstance(parsed, dict) else None
            if serif:
                dialogues.append({
                    "time": received,
                    "source": source,
                    "callback": event.get("callbackName"),
                    "text": serif,
                })
            elif parsed:
                issues.append({
                    "time": received,
                    "source": source,
                    "callback": event.get("callbackName"),
                    "plaintext": parsed,
                })
        elif operation == "command_message":
            command = parse_command(event.get("rawMessage"))
            if command:
                commands.append({
                    "time": received,
                    "source": source,
                    **command,
                })
        elif operation == "dom_snapshot":
            snapshots.append({
                "time": received,
                "source": source,
                "href": event.get("href"),
                "hash": event.get("hash"),
                "title": event.get("title"),
                "headings": event.get("headings"),
                "buttons": event.get("buttons"),
                "dialogs": event.get("dialogs"),
                "text": event.get("text"),
            })
        elif operation == "http_audit":
            http_audits.append({
                "time": received,
                "source": source,
                "method": event.get("method"),
                "url": event.get("url"),
                "status": event.get("status"),
                "requestBody": event.get("requestBody"),
                "responseBody": event.get("responseBody"),
            })
    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "dialogues": dialogues,
        "plaintextCallbacks": issues,
        "commands": commands,
        "domSnapshots": snapshots,
        "httpAudits": http_audits,
        "inventory": {
            item_id: {
                **value,
                "name": item_definitions.get(item_id, {}).get("name"),
                "description": item_definitions.get(item_id, {}).get("description"),
            }
            for item_id, value in inventory.items()
        },
        "wallet": {
            "freeSakuradite": wallet[0],
            "paidSakuradite": wallet[1],
            "gold": wallet[2],
            "skipTickets": wallet[3],
            "stamina": wallet[4],
            "maxStamina": wallet[5],
        },
    }


def write_markdown(report, path):
    lines = [
        "# Engine plaintext report",
        "",
        f"Generated: {report['generatedAt']}",
        "",
        "## Inventory",
        "",
        "| Item ID | Name | Quantity | Description |",
        "|---|---|---:|---|",
    ]
    for item_id, item in sorted(report["inventory"].items()):
        lines.append(
            f"| `{item_id}` | {item.get('name') or '-'} | "
            f"{item['quantity']} | {item.get('description') or '-'} |")
    lines.extend([
        "",
        f"Wallet: free={report['wallet']['freeSakuradite']}, "
        f"paid={report['wallet']['paidSakuradite']}, "
        f"gold={report['wallet']['gold']}, "
        f"tickets={report['wallet']['skipTickets']}, "
        f"stamina={report['wallet']['stamina']}/"
        f"{report['wallet']['maxStamina']}",
        "",
        "## Dialogues",
        "",
    ])
    for dialogue in report["dialogues"]:
        lines.extend([
            f"### {dialogue['time']} {dialogue['source']}",
            "",
            dialogue["text"],
            "",
        ])
    lines.extend(["## Plaintext callbacks", ""])
    for item in report["plaintextCallbacks"]:
        lines.append(
            f"- {item['time']} {item['source']} `{item['callback']}`: "
            f"`{json.dumps(item['plaintext'], ensure_ascii=False)}`")
    lines.extend(["", "## Commands", ""])
    for command in report["commands"]:
        lines.append(
            f"- {command['time']} {command['source']} "
            f"`{command['command']}` "
            f"`{json.dumps(command['parameters'], ensure_ascii=False)}`")
    lines.extend(["", "## DOM snapshots", ""])
    for snapshot in report["domSnapshots"]:
        lines.extend([
            f"### {snapshot['time']} {snapshot['source']}",
            "",
            f"- URL: `{snapshot['href']}`",
            f"- Route: `{snapshot['hash']}`",
            f"- Title: {snapshot['title']}",
            f"- Headings: {', '.join(snapshot['headings'] or []) or '-'}",
            f"- Buttons: {' | '.join(snapshot['buttons'] or []) or '-'}",
            f"- Dialogs: {' | '.join(snapshot['dialogs'] or []) or '-'}",
            "",
            snapshot["text"] or "",
            "",
        ])
    lines.extend(["", "## HTTP audits", ""])
    for audit in report["httpAudits"]:
        lines.extend([
            f"### {audit['time']} {audit['source']}",
            "",
            f"- {audit['method']} `{audit['url']}`",
            f"- Status: {audit['status']}",
            f"- Request: `{audit['requestBody']}`",
            "",
            "Response:",
            "",
            "```json",
            audit["responseBody"] or "",
            "```",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_directory")
    parser.add_argument("--masterdata", required=True)
    parser.add_argument("--state-db", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.capture_directory).resolve()
    events = read_json_lines(root / "engine-events.jsonl")
    masterdata = load_masterdata(Path(args.masterdata).resolve())
    report = build_report(events, masterdata, Path(args.state_db).resolve())
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = output.with_suffix(".md")
    write_markdown(report, markdown)
    print(json.dumps({
        "output": str(output),
        "markdown": str(markdown),
        "dialogues": len(report["dialogues"]),
        "commands": len(report["commands"]),
        "domSnapshots": len(report["domSnapshots"]),
        "httpAudits": len(report["httpAudits"]),
    }, indent=2))


if __name__ == "__main__":
    main()
