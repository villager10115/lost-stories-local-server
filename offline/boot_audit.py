"""Conservative offline startup dependency audit; never executes cached scripts."""
import argparse
import json
import re
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from static_server import StaticStore

STRINGS = re.compile(r"""["']([^"'\r\n]+)["']""")
AMD = re.compile(r"(?:define|require)\s*\(\s*\[([^\]]*)\]")
PAIRS = re.compile(r"""(?:["']([^"']+)["']|([A-Za-z_$][\w$]*))\s*:\s*["']([^"']+)["']""")


def audit(root, entry):
    store = StaticStore(root, entry)
    manifest = json.loads((Path(root) / "routes.json").read_text(encoding="utf-8"))
    selected = next(e for e in manifest["entries"] if e["source"] == entry)
    refs = selected["references"]
    paths, stamps = {}, {}
    for ref in refs:
        target = ref["path"] + ("?rev=" + ref["rev"] if ref["rev"] else "")
        status, body, _ = store.resolve(target)
        if status != 200:
            continue
        source = body.decode("utf-8")
        if ref["path"].endswith("/replacement.js"):
            match = re.search(r"\bfileTimeStamp\s*=\s*(\{[^}]*\})", source)
            if match:
                stamps = json.loads(match.group(1))
        if ref["path"].endswith("/baseConfig.js"):
            for match in re.finditer(r"path(?:Black|White)List\s*=\s*\{([^}]+)\}", source):
                paths.update({a or b: c for a, b, c in PAIRS.findall(match.group(1))})
    queue = deque((r["path"], r["rev"], "entry") for r in refs)
    seen, checked, unresolved = set(), [], []
    while queue:
        path, rev, parent = queue.popleft()
        if (path, rev) in seen:
            continue
        seen.add((path, rev))
        target = path + ("?rev=" + rev if rev else "")
        status, body, _ = store.resolve(target)
        checked.append({"path": path, "rev": rev, "status": status, "parent": parent})
        if status != 200 or not path.endswith((".js", ".css")):
            continue
        source = body.decode("utf-8")
        dependencies = []
        if path.endswith(".js"):
            for group in AMD.findall(source):
                for name in STRINGS.findall(group):
                    if name in ("require", "exports", "module"):
                        continue
                    if "!" in name:
                        plugin, name = name.split("!", 1)
                        if plugin != "text":
                            unresolved.append({"parent": path, "dependency": name, "reason": "unknown plugin"})
                            continue
                        dependencies.append((paths.get(plugin, plugin), True))
                        dependencies.append((name, False))
                    else:
                        dependencies.append((paths.get(name, name), True))
            for name, javascript in dependencies:
                if "<" in name or ">" in name:
                    unresolved.append({"parent": path, "dependency": name, "reason": "dynamic reference"})
                    continue
                if javascript and not name.endswith(".js"):
                    name += ".js"
                resolved = urlsplit(urljoin("https://offline.invalid" + (path if name.startswith(".") else "/web/"), name))
                if resolved.netloc != "offline.invalid":
                    unresolved.append({"parent": path, "dependency": name, "reason": "external"})
                    continue
                query = parse_qs(resolved.query)
                version = query.get("rev", [stamps.get(resolved.path.removeprefix("/web/"))])[0]
                queue.append((resolved.path, version, path))
        else:
            for name in re.findall(r"""url\(\s*["']?([^)"'\s]+)""", source):
                if name.startswith(("data:", "#")):
                    continue
                resolved = urlsplit(urljoin("https://offline.invalid" + path, name))
                if resolved.netloc != "offline.invalid":
                    unresolved.append({"parent": path, "dependency": name, "reason": "external"})
                    continue
                queue.append((resolved.path, parse_qs(resolved.query).get("rev", [None])[0], path))
    available = {}
    for route in manifest["routes"]:
        available.setdefault(route["path"], []).append(route["rev"])
    for record in checked:
        if record["status"] != 200:
            record["available_revisions"] = available.get(record["path"], [])
            record["reason"] = ("ambiguous" if record["status"] == 409 else
                                "version_mismatch" if record["available_revisions"] else
                                "not_staged")
    return {"entry": entry, "timestamp_count": len(stamps), "alias_count": len(paths),
            "checked": checked, "unresolved": unresolved,
            "blocked": [r for r in checked if r["status"] != 200],
            "limitations": "Static literal AMD arrays and CSS URLs only; dynamic requests, templates and native bridge are not validated."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.root, args.entry)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Checked:", len(report["checked"]), "Blocked:", len(report["blocked"]),
          "Unresolved:", len(report["unresolved"]))
