import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


LINK_PATTERN = re.compile(r'([A-Za-z0-9_]+):"(/[^"]+)"')
MODEL_ID_PATTERN = re.compile(r'\{id:"([^"]+)"(?:,refresh:!?[01truefals]+)?\}')
TEMPLATE_PAGE_PATTERN = re.compile(
    r'text!template/[^"/]+/([^"/]+)\.html')
IMPLEMENTED_ROUTE_PATTERN = re.compile(r'"(/api/[^"?]+)"')


def stable_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_latest_link_list(web_root, minimum_links=100):
    for path in sorted(web_root.rglob("*"), key=lambda item: item.stat().st_mtime
                       if item.is_file() else 0, reverse=True):
        if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if 'gachaDraw:"/gacha/draw"' not in text:
            continue
        start = text.find("r={")
        end = text.find("};return e.linkList", start)
        if start < 0 or end < 0:
            continue
        body = text[start:end]
        links = {
            key: value for key, value in LINK_PATTERN.findall(body)
            if value.startswith("/")
        }
        if len(links) >= minimum_links:
            return path, links
    raise RuntimeError("Could not locate the client linkList definition")


def balanced_slice(text, start):
    pairs = {"(": ")", "[": "]", "{": "}"}
    if start >= len(text) or text[start] not in pairs:
        raise ValueError("balanced_slice must start on an opening delimiter")
    stack = [pairs[text[start]]]
    quote = None
    escaped = False
    index = start + 1
    while index < len(text):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char in ('"', "'", "`"):
                quote = char
            elif char in pairs:
                stack.append(pairs[char])
            elif stack and char == stack[-1]:
                stack.pop()
                if not stack:
                    return text[start + 1:index], index
        index += 1
    raise ValueError("Unclosed delimiter")


def split_arguments(value):
    parts = []
    start = 0
    stack = []
    quote = None
    escaped = False
    pairs = {"(": ")", "[": "]", "{": "}"}
    for index, char in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'", "`"):
            quote = char
        elif char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        elif char == "," and not stack:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def extract_ajax_calls(text, source_name):
    calls = []
    pattern = re.compile(r"\.?(ajaxPost|ajaxGet)\s*\(")
    for match in pattern.finditer(text):
        try:
            arguments, _ = balanced_slice(text, match.end() - 1)
        except ValueError:
            continue
        parts = split_arguments(arguments)
        if len(parts) < 2:
            continue
        link_match = re.search(r"linkList\.([A-Za-z0-9_]+)", parts[0])
        if not link_match:
            continue
        calls.append({
            "key": link_match.group(1),
            "method": "POST" if match.group(1) == "ajaxPost" else "GET",
            "bodyExpression": re.sub(r"\s+", " ", parts[1]).strip()[:3000],
            "source": source_name,
        })
    return calls


def extract_page_models(text, source_name):
    marker = text.find("needModelIdObj:")
    if marker < 0:
        return None
    bracket = text.find("[", marker)
    if bracket < 0:
        return None
    try:
        body, _ = balanced_slice(text, bracket)
    except ValueError:
        return None
    models = []
    for item in MODEL_ID_PATTERN.finditer(body):
        if item.group(1) not in models:
            models.append(item.group(1))
    template = TEMPLATE_PAGE_PATTERN.search(text)
    return {
        "page": template.group(1) if template else None,
        "models": models,
        "source": source_name,
        "inferred": True,
    }


def implemented_routes(server_path):
    if not server_path.exists():
        return set()
    text = server_path.read_text(encoding="utf-8")
    return set(IMPLEMENTED_ROUTE_PATTERN.findall(text))


def preserved_page_paths(manifest_path):
    if not manifest_path or not manifest_path.exists():
        return set()
    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        record["path"] for record in records
        if record.get("host") == "app.lost-stories.net"
        and record.get("path", "").startswith("/api/page/")
    }


def build_schema(web_root, server_path, minimum_links=100,
                 preserved_manifest=None):
    link_source, links = find_latest_link_list(web_root, minimum_links)
    endpoint_calls = {}
    page_modules = []
    files_scanned = 0
    for path in web_root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            continue
        relative = path.relative_to(web_root).as_posix()
        if path.suffix not in {".js", ""} and "bodies" not in relative:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files_scanned += 1
        for call in extract_ajax_calls(text, relative):
            endpoint_calls.setdefault(call.pop("key"), []).append(call)
        page = extract_page_models(text, relative)
        if page and page["models"]:
            page_modules.append(page)

    implemented = implemented_routes(server_path)
    preserved_pages = preserved_page_paths(preserved_manifest)
    endpoints = []
    for key, suffix in sorted(links.items()):
        path = "/api" + suffix
        calls = endpoint_calls.get(key, [])
        endpoints.append({
            "key": key,
            "path": path,
            "implementedLocally": (
                path in implemented or
                path in preserved_pages or
                any(route.rstrip("/") == path.rstrip("/") for route in implemented)
            ),
            "preservedPage": path in preserved_pages,
            "observedMethods": sorted({call["method"] for call in calls}),
            "calls": calls,
        })

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceWebRoot": str(web_root),
        "linkListSource": str(link_source),
        "linkListSourceSha256": stable_hash(link_source),
        "filesScanned": files_scanned,
        "headerContract": [
            "F4-Access-Token",
            "X-User-Identity",
            "X-App-Ver",
            "X-PlatForm",
            "X-Client-Model-Name",
            "X-Client-OS-Ver",
            "X-Viewer-Identity",
            "X-Onetime-Token",
            "X-Web-Session-Id",
            "X-Request-Id",
        ],
        "requestEncoding": {
            "POST": {
                "objectContentType": "application/JSON",
                "objectBody": "JSON.stringify(body)",
                "stringContentType": "text/plain",
                "stringBody": "String(body)",
            },
            "GET": {
                "body": "none",
                "urlSuffix": "/<argument> when the second argument is non-empty",
            },
        },
        "endpointCount": len(endpoints),
        "implementedEndpointCount": sum(
            1 for endpoint in endpoints if endpoint["implementedLocally"]),
        "endpoints": endpoints,
        "pageModelRequests": page_modules,
    }


def write_markdown(schema, path):
    lines = [
        "# Client request schema",
        "",
        f"Generated: {schema['generatedAt']}",
        "",
        f"Endpoints: {schema['endpointCount']}; implemented locally: "
        f"{schema['implementedEndpointCount']}",
        "",
        "## Headers",
        "",
    ]
    lines.extend(f"- `{header}`" for header in schema["headerContract"])
    lines.extend(["", "## Endpoints", "",
                  "| Key | Path | Methods | Implemented | Body call sites |",
                  "|---|---|---|---:|---:|"])
    for endpoint in schema["endpoints"]:
        lines.append(
            f"| `{endpoint['key']}` | `{endpoint['path']}` | "
            f"{', '.join(endpoint['observedMethods']) or '-'} | "
            f"{'yes' if endpoint['implementedLocally'] else 'no'} | "
            f"{len(endpoint['calls'])} |")
    lines.extend(["", "## Observed request body expressions", ""])
    for endpoint in schema["endpoints"]:
        bodies = {
            call["bodyExpression"]
            for call in endpoint["calls"]
            if call["method"] == "POST"
        }
        if not bodies:
            continue
        lines.append(f"### `{endpoint['path']}`")
        lines.append("")
        for body in sorted(bodies):
            lines.append(f"- `{body[:1200]}`")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-root", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--preserved-manifest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown")
    arguments = parser.parse_args()
    web_root = Path(arguments.web_root).resolve()
    server_path = Path(arguments.server).resolve()
    output = Path(arguments.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    preserved_manifest = (
        Path(arguments.preserved_manifest).resolve()
        if arguments.preserved_manifest else None
    )
    schema = build_schema(web_root, server_path,
                          preserved_manifest=preserved_manifest)
    output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = Path(arguments.markdown).resolve() if arguments.markdown else (
        output.with_suffix(".md"))
    write_markdown(schema, markdown)
    print(json.dumps({
        "output": str(output),
        "markdown": str(markdown),
        "endpointCount": schema["endpointCount"],
        "implementedEndpointCount": schema["implementedEndpointCount"],
        "pageModelRequests": len(schema["pageModelRequests"]),
    }, indent=2))


if __name__ == "__main__":
    main()
