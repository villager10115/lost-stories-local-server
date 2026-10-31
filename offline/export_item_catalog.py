import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("masterdata")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()
    masterdata = json.loads(
        Path(args.masterdata).read_text(encoding="utf-8"))
    items = sorted(
        masterdata.get("itemList", []),
        key=lambda item: item.get("itemId", ""),
    )
    records = [
        {
            "itemId": item.get("itemId"),
            "name": item.get("name"),
            "description": item.get("description"),
            "itemType": item.get("itemType"),
        }
        for item in items
    ]
    json_output = Path(args.json_output).resolve()
    markdown_output = Path(args.markdown_output).resolve()
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Item catalog",
        "",
        f"Items: {len(records)}",
        "",
        "| Item ID | Name | Type | Description |",
        "|---|---|---|---|",
    ]
    for item in records:
        description = (item["description"] or "").replace("\n", " ")
        lines.append(
            f"| `{item['itemId']}` | {item['name'] or '-'} | "
            f"{item['itemType'] or '-'} | {description or '-'} |")
    markdown_output.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "json": str(json_output),
        "markdown": str(markdown_output),
        "items": len(records),
    }, indent=2))


if __name__ == "__main__":
    main()
