import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


REMOTE_BASE = "https://app.lost-stories.net/web/index.html"


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


def local_target(base_url, remote_url):
    parsed = urlsplit(urljoin(REMOTE_BASE, remote_url))
    path = parsed.path
    if path.startswith("/api/"):
        local_path = path
    elif path.startswith("/web/"):
        local_path = path
    elif path.startswith("/json/"):
        local_path = "/web" + path
    else:
        local_path = "/web/" + path.lstrip("/")
    query = ("?" + parsed.query) if parsed.query else ""
    return base_url.rstrip("/") + local_path + query, local_path


def probe(url):
    request = Request(url, headers={
        "X-Web-Session-Id": "network-structure-audit",
        "Accept": "*/*",
    })
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            return {
                "status": response.status,
                "bytesRead": len(body),
                "contentType": response.headers.get("Content-Type"),
            }
    except HTTPError as error:
        return {
            "status": error.code,
            "bytesRead": 0,
            "contentType": error.headers.get("Content-Type"),
        }
    except (URLError, TimeoutError, OSError) as error:
        return {
            "status": None,
            "bytesRead": 0,
            "contentType": None,
            "error": str(error),
        }


def network_endpoints(network_events):
    dns = {}
    for event in network_events:
        if event.get("kind") == "dns" and event.get("data"):
            dns.setdefault(event["data"], set()).add(event.get("name"))
    endpoints = {}
    for event in network_events:
        if event.get("kind") != "tcp" or event.get("client") != "official":
            continue
        address = event.get("remote_address")
        port = event.get("remote_port")
        if not address or not port or address.startswith("127."):
            continue
        key = f"{address}:{port}"
        row = endpoints.setdefault(key, {
            "endpoint": key,
            "processes": set(),
            "pids": set(),
        })
        if event.get("process"):
            row["processes"].add(event["process"])
        if event.get("pid"):
            row["pids"].add(event["pid"])
    return [
        {
            "endpoint": row["endpoint"],
            "domains": sorted(dns.get(row["endpoint"].rsplit(":", 1)[0], [])),
            "processes": sorted(row["processes"]),
            "pids": sorted(row["pids"]),
        }
        for _, row in sorted(endpoints.items())
    ]


def write_markdown(report, path):
    lines = [
        "# Offline network structure",
        "",
        f"Generated: {report['generatedAt']}",
        "",
        f"Checks: {report['checkCount']}; "
        f"successful: {report['successCount']}; "
        f"failed: {report['failedCount']}",
        "",
        "## Remote endpoint mapping",
        "",
        "| Remote endpoint | DNS names | Process |",
        "|---|---|---|",
    ]
    for endpoint in report["remoteEndpoints"]:
        lines.append(
            f"| {endpoint['endpoint']} | "
            f"{', '.join(endpoint['domains']) or 'unresolved'} | "
            f"{', '.join(endpoint['processes']) or '-'} |")
    lines.extend([
        "",
        "## Local request order",
        "",
        "| Order | Official request | Local target | Status | Bytes |",
        "|---:|---|---|---:|---:|",
    ])
    for row in report["requests"]:
        lines.append(
            f"| {row['order']} | `{row['officialUrl']}` | "
            f"`{row['localUrl']}` | {row['probe'].get('status')} | "
            f"{row['probe'].get('bytesRead')} |")
    lines.extend(["", "## Failures", ""])
    failures = [row for row in report["requests"]
                if row["probe"].get("status") != 200]
    if not failures:
        lines.append("- None.")
    else:
        for row in failures:
            lines.append(
                f"- {row['officialUrl']} -> {row['localUrl']}: "
                f"{row['probe']}")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_directory")
    parser.add_argument("--base-url", default="http://127.0.0.1:18865")
    parser.add_argument("--local-load-order")
    parser.add_argument("--routes-manifest")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.capture_directory).resolve()
    engine_events = read_json_lines(root / "engine-events.jsonl")
    network_events = read_json_lines(root / "network-events.jsonl")

    captured_urls = []
    startup_urls = []
    route_urls = []
    seen = set()
    for event in engine_events:
        if event.get("source") != "official":
            continue
        if event.get("operation") == "http_audit":
            url = event.get("url")
        elif event.get("kind") == "request" and event.get("url"):
            url = event["url"]
        else:
            continue
        if not isinstance(url, str) or url in seen:
            continue
        seen.add(url)
        captured_urls.append(url)

    if args.local_load_order:
        local_order = json.loads(
            Path(args.local_load_order).read_text(encoding="utf-8"))
        for request in local_order.get("requests", []):
            url = request.get("url")
            if not isinstance(url, str) or not url.startswith(
                    args.base_url.rstrip("/") + "/"):
                continue
            relative = url[len(args.base_url.rstrip("/")):]
            if relative not in seen:
                seen.add(relative)
                startup_urls.append(relative)

    if args.routes_manifest:
        routes = json.loads(
            Path(args.routes_manifest).read_text(encoding="utf-8"))
        for route in routes.get("routes", []):
            path = route.get("path")
            revision = route.get("rev")
            if not isinstance(path, str) or not path.startswith("/web/"):
                continue
            url = path
            if revision is not None:
                url += "?rev=" + str(revision)
            if url in seen:
                continue
            seen.add(url)
            route_urls.append(url)

    official_urls = startup_urls + captured_urls + route_urls

    requests = []
    for index, official_url in enumerate(official_urls, start=1):
        local_url, local_path = local_target(args.base_url, official_url)
        requests.append({
            "order": index,
            "officialUrl": official_url,
            "localPath": local_path,
            "localUrl": local_url,
            "probe": probe(local_url),
        })

    result = {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "baseUrl": args.base_url,
        "checkCount": len(requests),
        "successCount": sum(
            1 for row in requests if row["probe"].get("status") == 200),
        "failedCount": sum(
            1 for row in requests if row["probe"].get("status") != 200),
        "remoteEndpoints": network_endpoints(network_events),
        "requests": requests,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = output.with_suffix(".md")
    write_markdown(result, markdown)
    print(json.dumps({
        "output": str(output),
        "markdown": str(markdown),
        "checks": result["checkCount"],
        "successful": result["successCount"],
        "failed": result["failedCount"],
        "remoteEndpoints": len(result["remoteEndpoints"]),
    }, indent=2))


if __name__ == "__main__":
    main()
