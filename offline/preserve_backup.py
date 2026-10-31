"""Copy preservation data without overwrites, then verify every file by SHA-256."""
import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def preserve(source, destination, report, expected=None):
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and destination must not overlap")
    destination.mkdir(parents=True, exist_ok=True)
    reference = {}
    if expected:
        with expected.open(encoding="utf-8-sig", newline="") as stream:
            reference = {r["RelativePath"].replace("\\", "/"): r["SHA256"].lower()
                         for r in csv.DictReader(stream)}
    count = total = errors = 0
    seen = set()
    with report.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["RelativePath", "Bytes", "SHA256", "Verified", "Error"])
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            seen.add(relative)
            target = destination / relative
            size, checksum, error = 0, "", ""
            try:
                if path.is_symlink():
                    raise ValueError("Symlink requires manual preservation")
                before = path.stat()
                size = before.st_size
                checksum = digest(path)
                if relative in reference and checksum != reference[relative]:
                    raise ValueError("Source differs from original manifest")
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    partial = target.with_name(target.name + ".preserving")
                    if partial.exists():
                        raise ValueError("Partial copy already exists; inspect manually")
                    shutil.copy2(path, partial)
                    partial.rename(target)
                if digest(target) != checksum:
                    raise ValueError("Destination hash mismatch; existing file not overwritten")
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("Source changed during preservation")
            except (OSError, ValueError) as exc:
                error = str(exc)
                errors += 1
            writer.writerow([relative, size, checksum, not error, error])
            count += 1
            total += size
            if count % 5000 == 0:
                stream.flush()
                print(f"{source.name}: {count} files, {errors} errors", flush=True)
        for missing in sorted(reference.keys() - seen):
            writer.writerow([missing, 0, "", False, "Missing from source"])
            errors += 1
    result = dict(source=str(source), destination=str(destination), files=count,
                  bytes=total, errors=errors, completedUTC=datetime.now(timezone.utc).isoformat())
    report.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()
    if not args.source.is_dir():
        parser.error("Source directory does not exist")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    raise SystemExit(bool(preserve(args.source, args.destination, args.report, args.expected)))


if __name__ == "__main__":
    main()
