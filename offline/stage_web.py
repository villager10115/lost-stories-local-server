"""Stage cached static assets only. Ambiguous versions are never silently selected."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs
from web_audit import decode_text, References


def stage(source, output):
    records = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    index = {}
    for record in records:
        if record["path"].startswith("/web/"):
            key = (record["path"], record.get("rev"))
            index.setdefault(key, {})[record["sha256"]] = record
    output.mkdir(parents=True, exist_ok=True)
    bodies = output / "bodies"
    bodies.mkdir(exist_ok=True)
    routes, conflicts, entries = [], [], []
    for (path, rev), variants in sorted(index.items(), key=lambda x: str(x[0])):
        if len(variants) != 1:
            conflicts.append({"path": path, "rev": rev, "variants": len(variants)})
            continue
        record = next(iter(variants.values()))
        body = (source / (record["sha256"] + ".body")).read_bytes()
        if hashlib.sha256(body).hexdigest() != record["sha256"]:
            raise ValueError("Source checksum mismatch")
        if path.endswith((".html", ".js", ".css", ".json", ".svg")):
            body = decode_text(body)[0].encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        (bodies / digest).write_bytes(body)
        routes.append({"path": path, "rev": rev, "body": digest})
    # Index pages have multiple historical versions: retain them as explicit choices.
    for (path, rev), variants in index.items():
        if path != "/web/index.html":
            continue
        for digest, record in variants.items():
            text, _ = decode_text((source / (digest + ".body")).read_bytes())
            parser = References()
            parser.feed(text)
            refs = []
            for ref in parser.references:
                url = urlsplit(urljoin("https://" + record["host"] + path, ref))
                wanted = parse_qs(url.query).get("rev", [None])[0]
                candidates = index.get((url.path, wanted), {})
                refs.append({"path": url.path, "rev": wanted,
                             "exact_unique_match": url.hostname == record["host"] and len(candidates) == 1})
            body = text.encode("utf-8")
            output_hash = hashlib.sha256(body).hexdigest()
            (bodies / output_hash).write_bytes(body)
            entries.append({"source": digest, "body": output_hash, "references": refs,
                            "direct_dependencies_complete": all(r["exact_unique_match"] for r in refs)})
    manifest = {"routes": routes, "conflicts": conflicts, "entries": entries,
                "warning": "Static preview only; no API or native bridge implementation"}
    (output / "routes.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Static routes:", len(routes), "ambiguous routes:", len(conflicts))
    print("Entry variants:", len(entries), "with exact direct dependencies:",
          sum(e["direct_dependencies_complete"] for e in entries))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    stage(args.source, args.output)
