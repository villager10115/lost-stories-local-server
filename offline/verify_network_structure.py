import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    manifest = json.loads(
        Path(args.manifest).read_text(encoding="utf-8"))
    failures = []
    checked = 0
    for row in manifest.get("requests", []):
        local = urlsplit(row["localUrl"])
        target = (
            args.base_url.rstrip("/") + local.path
            + (("?" + local.query) if local.query else "")
        )
        request = Request(target, headers={
            "X-Web-Session-Id": "offline-network-preflight",
            "Accept": "*/*",
        })
        checked += 1
        try:
            with urlopen(request, timeout=10) as response:
                response.read(1)
                if response.status != 200:
                    failures.append({
                        "target": target,
                        "status": response.status,
                    })
        except HTTPError as error:
            failures.append({
                "target": target,
                "status": error.code,
            })
        except (URLError, TimeoutError, OSError) as error:
            failures.append({
                "target": target,
                "status": None,
                "error": str(error),
            })
    result = {
        "checked": checked,
        "successful": checked - len(failures),
        "failed": len(failures),
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
