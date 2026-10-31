"""Collect a bounded batch of known missing static assets; never send credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def collect(audit_path, output, limit=20):
    if not 1 <= limit <= 100:
        raise ValueError("Batch limit must be 1..100")
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    targets = []
    for row in audit["blocked"]:
        path, rev = row["path"], row.get("rev")
        url = urlsplit(path)
        if (url.scheme or url.netloc or url.query or url.fragment
                or not path.startswith("/web/") or ".." in path
                or not path.endswith((".js", ".css", ".html", ".webp", ".png", ".json", ".woff2"))):
            continue
        if rev is not None and not all(c in "0123456789abcdef" for c in rev):
            continue
        if (path, rev) not in targets:
            targets.append((path, rev))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    opener = build_opener(NoRedirect())
    reports = []
    for path, rev in targets[:limit]:
        url = "https://app.lost-stories.net" + path + ("?rev=" + rev if rev else "")
        row = {"path": path, "rev": rev, "credentials_sent": False,
               "historical_version_verified": False}
        try:
            with opener.open(Request(url, headers={"User-Agent": "ResourcePreservationCheck/1.0"}),
                             timeout=25) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                row.update(status=response.status, bytes=len(raw),
                           content_type=response.headers.get("Content-Type"))
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError("Response size limit")
                digest = hashlib.sha256(raw).hexdigest()
                (output / (digest + ".body")).write_bytes(raw)
                row["sha256"] = digest
        except HTTPError as error:
            row.update(status=error.code, error="HTTP refused; redirects disabled")
        except Exception as error:
            row["error_type"] = type(error).__name__
        reports.append(row)
        (output / "report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
        time.sleep(0.5)
    print(json.dumps({"attempted": len(reports),
                      "downloaded": sum("sha256" in row for row in reports),
                      "remaining_unattempted": max(0, len(targets) - limit)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    collect(args.audit, args.output, args.limit)
