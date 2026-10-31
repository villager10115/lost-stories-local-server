import json
import sys
from pathlib import Path


CLIENTS = {
    "official": "official",
    "packaged-local": "local",
}


def split_json_lines(source, destination, client):
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with source.open(encoding="utf-8") as input_stream, \
            destination.open("w", encoding="utf-8") as output_stream:
        for line in input_stream:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("source", event.get("client")) != client:
                continue
            output_stream.write(
                json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python split_capture_logs.py OUTPUT_DIRECTORY")
    root = Path(sys.argv[1]).resolve()
    mappings = [
        ("engine-events.jsonl", "engine-events.jsonl"),
        ("click-events.jsonl", "click-events.jsonl"),
        ("native-clicks.jsonl", "native-clicks.jsonl"),
        ("network-events.jsonl", "network-events.jsonl"),
    ]
    summary = {}
    for source_name, destination_name in mappings:
        source = root / source_name
        if not source.exists():
            continue
        for client, directory_name in CLIENTS.items():
            destination = root / directory_name / destination_name
            count = split_json_lines(source, destination, client)
            summary[f"{directory_name}/{destination_name}"] = count
    (root / "split-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
