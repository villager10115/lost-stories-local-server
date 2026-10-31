"""Build a clean portable ZIP that does not carry a local account.

The archive keeps the client, runtime, server code and static resources, while
excluding formal saves, browser state, logs, snapshots and account-only reports.
Known local account identifiers and captured `user*` page state are removed from
the archive copies.  The installed package is never modified.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

from web_audit import decode_text


KNOWN_ACCOUNT_IDS = (
    "00000000-0000-0000-0000-000000000000",
)
REDACTED_ACCOUNT_ID = "00000000-0000-0000-0000-000000000000"
TEXT_SUFFIXES = {
    ".css",
    ".cs",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".txt",
}
EXCLUDED_TOP_LEVEL = {
    "build-source",
    "data",
    "logs",
    "research",
    "run",
    "snapshots",
}
EXCLUDED_TOP_LEVEL_FILES = {
    "PROGRESS.md",
    "KMF_MANAGEMENT_20261031.md",
    "DS_OFFLINE_REPAIR_20261031.md",
    "ロストストーリーズ.lnk",
}
INCLUDED_TOP_LEVEL = {
    "app",
    "assets",
    "Client",
    "config",
    "launcher",
    "runtime",
}
ACCOUNT_KEYS = {
    "gameUser",
    "guild",
    "guildMember",
    "guildMemberList",
    "guildMemberNum",
    "presentCount",
    "roomId",
    "unapprovedList",
    "user",
}
EMPTY_DIRECTORIES = (
    "data/native",
    "data/page",
    "data/state",
    "logs",
    "run",
    "snapshots",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_page_selections(source: Path) -> dict[str, str]:
    module = (source / "offline" / "preserved_pages.py").read_text("utf8")
    tree = ast.parse(module)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
                isinstance(target, ast.Name)
                and target.id == "PAGE_SELECTIONS"
                for target in node.targets):
            return dict(ast.literal_eval(node.value))
    raise RuntimeError("PAGE_SELECTIONS was not found")


def strip_account_state(data: dict) -> bool:
    changed = False
    for key in list(data):
        if key in ACCOUNT_KEYS or key.startswith("user"):
            data.pop(key, None)
            changed = True
    return changed


def sanitize_body(raw: bytes, force: bool) -> tuple[bytes, bool]:
    try:
        text, _ = decode_text(raw)
        data = json.loads(text)
    except Exception:
        return raw, False
    if not isinstance(data, dict):
        return raw, False
    changed = strip_account_state(data)
    if not force and not changed:
        return raw, False
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    for account_id in KNOWN_ACCOUNT_IDS:
        encoded = encoded.replace(
            account_id.encode("ascii"),
            REDACTED_ACCOUNT_ID.encode("ascii"),
        )
    return encoded, True


def sanitize_preserved_pages(
    source: Path,
) -> tuple[dict[str, bytes], set[str], dict[str, str], dict[str, str]]:
    app_root = source / "app" if (source / "app" / "offline").is_dir() else source
    cache = source / "assets" / "preserved-pages"
    manifest_path = cache / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf8"))
    if not isinstance(manifest, list):
        raise RuntimeError("Invalid preserved-pages manifest")

    selections = load_page_selections(app_root)
    selected_digests = set(selections.values())
    body_overrides: dict[str, bytes] = {}
    replaced_digests: dict[str, str] = {}
    skip_paths: set[str] = set()

    for body_path in cache.glob("*.body"):
        old_digest = body_path.stem
        raw = body_path.read_bytes()
        sanitized, changed = sanitize_body(
            raw, old_digest in selected_digests)
        if not changed:
            continue
        new_digest = sha256_bytes(sanitized)
        replaced_digests[old_digest] = new_digest
        skip_paths.add("assets/preserved-pages/" + body_path.name)
        body_overrides[
            "assets/preserved-pages/" + new_digest + ".body"
        ] = sanitized

    for record in manifest:
        if not isinstance(record, dict):
            continue
        old_digest = record.get("sha256")
        new_digest = replaced_digests.get(old_digest)
        if new_digest is None:
            continue
        body = body_overrides[
            "assets/preserved-pages/" + new_digest + ".body"
        ]
        record["sha256"] = new_digest
        record["bytes"] = len(body)

    body_overrides["assets/preserved-pages/manifest.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    skip_paths.add("assets/preserved-pages/manifest.json")

    preserved_pages_py = app_root / "offline" / "preserved_pages.py"
    patched = preserved_pages_py.read_text("utf8")
    for old_digest, new_digest in replaced_digests.items():
        patched = patched.replace(old_digest, new_digest)
    body_overrides["app/offline/preserved_pages.py"] = patched.encode("utf-8")
    skip_paths.add("app/offline/preserved_pages.py")
    return body_overrides, skip_paths, replaced_digests, selections


def is_excluded(relative: str) -> bool:
    path = Path(relative)
    parts = path.parts
    if not parts:
        return True
    if parts[0] in EXCLUDED_TOP_LEVEL:
        return True
    if len(parts) == 1 and relative in EXCLUDED_TOP_LEVEL_FILES:
        return True
    if any(part == "__pycache__" for part in parts):
        return True
    if path.suffix.lower() in {".pyc", ".tmp"}:
        return True
    if path.name.endswith((".log", ".tmp", ".before")):
        return True
    if parts[0] == "reports":
        return relative not in {
            "reports/ENHANCEMENT_ALL_MODULES_20261031.md",
            "reports/no-account-package.json",
            "reports/files.json",
        }
    if parts[0] == "app":
        if "tests" in parts:
            return True
        if path.name.startswith("test_"):
            return True
        if path.name.endswith(("_test.py", "_test.js")):
            return True
    return False


def collect_source_files(
    source: Path,
    skip_paths: set[str],
) -> list[str]:
    result = []
    for top in sorted(INCLUDED_TOP_LEVEL):
        root = source / top
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            if relative in skip_paths or is_excluded(relative):
                continue
            result.append(relative)
    for name in (
        "README_日本語.md",
        "reports/ENHANCEMENT_ALL_MODULES_20261031.md",
    ):
        if (source / name).is_file():
            result.append(name)
    return sorted(result)


def redact_known_ids(relative: str, data: bytes) -> tuple[bytes, int]:
    if Path(relative).suffix.lower() not in TEXT_SUFFIXES:
        return data, 0
    count = 0
    for account_id in KNOWN_ACCOUNT_IDS:
        occurrences = data.count(account_id.encode("ascii"))
        if not occurrences:
            continue
        data = data.replace(
            account_id.encode("ascii"),
            REDACTED_ACCOUNT_ID.encode("ascii"),
        )
        count += occurrences
    return data, count


def add_bytes(
    archive: zipfile.ZipFile,
    root_name: str,
    relative: str,
    data: bytes,
    manifest_files: list[dict],
) -> None:
    arcname = root_name + "/" + relative
    digest = sha256_bytes(data)
    archive.writestr(arcname, data)
    manifest_files.append({
        "path": relative,
        "bytes": len(data),
        "sha256": digest,
    })


def add_file(
    archive: zipfile.ZipFile,
    root_name: str,
    source: Path,
    relative: str,
    manifest_files: list[dict],
    progress: dict,
) -> None:
    path = source / relative
    arcname = root_name + "/" + relative
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES and path.stat().st_size <= 20 * 1024 * 1024:
        data, redactions = redact_known_ids(relative, path.read_bytes())
        if redactions:
            progress["redactedFiles"] += 1
            progress["redactedIds"] += redactions
        add_bytes(archive, root_name, relative, data, manifest_files)
        progress["bytes"] += len(data)
        progress["files"] += 1
        return

    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as src, archive.open(arcname, "w") as dst:
        for chunk in iter(lambda: src.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
            dst.write(chunk)
            size += len(chunk)
            progress["bytes"] += len(chunk)
    manifest_files.append({
        "path": relative,
        "bytes": size,
        "sha256": digest.hexdigest(),
    })
    progress["files"] += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(r"D:\LostStories_Japanese"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            r"D:\codegeass\LostStories_Japanese_Clean_NoAccount_20261031.zip"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output.resolve()

    body_overrides, skip_paths, replaced, selections = \
        sanitize_preserved_pages(source)
    source_files = collect_source_files(source, skip_paths)
    source_bytes = sum((source / relative).stat().st_size
                       for relative in source_files)
    override_bytes = sum(len(value) for value in body_overrides.values())
    estimated_files = len(source_files) + len(body_overrides) + 4
    estimated_bytes = source_bytes + override_bytes

    build_info = {
        "source": str(source),
        "builtAt": datetime.now().astimezone().isoformat(),
        "accountDataIncluded": False,
        "excludedRoots": sorted(EXCLUDED_TOP_LEVEL),
        "excludedFiles": sorted(EXCLUDED_TOP_LEVEL_FILES),
        "emptyDirectories": list(EMPTY_DIRECTORIES),
        "knownAccountIdsRedacted": list(KNOWN_ACCOUNT_IDS),
        "sanitizedPreservedBodies": len(replaced),
        "selectedPreservedPagesRewritten": len(selections),
        "estimatedFiles": estimated_files,
        "estimatedBytes": estimated_bytes,
    }
    print(json.dumps(build_info, ensure_ascii=False), flush=True)
    if args.dry_run:
        return 0
    if output.exists():
        raise RuntimeError("Output ZIP already exists: " + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)

    root_name = "LostStories_Japanese"
    manifest_files: list[dict] = []
    progress = {
        "files": 0,
        "bytes": 0,
        "redactedFiles": 0,
        "redactedIds": 0,
    }
    report_relative = "reports/no-account-package.json"
    readme_relative = "NO_ACCOUNT_README.txt"
    readme = (
        "This package starts with a new local account.\n"
        "No existing state/page/deck database, browser cache, log, or "
        "snapshot is included.\n"
        "On first launch the client creates fresh data under data/.\n"
    ).encode("utf-8")

    file_handle = output.open("wb")
    zip_digest = hashlib.sha256()

    class HashingWriter:
        def write(self, data):
            written = file_handle.write(data)
            zip_digest.update(data[:written])
            return written

        def flush(self):
            file_handle.flush()

        def tell(self):
            return file_handle.tell()

        def seek(self, offset, whence=0):
            return file_handle.seek(offset, whence)

        def close(self):
            file_handle.close()

    try:
        writer = HashingWriter()
        with zipfile.ZipFile(
                writer,
                mode="w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True) as archive:
            for directory in EMPTY_DIRECTORIES:
                archive.writestr(root_name + "/" + directory + "/", b"")

            last_report = 0
            for relative in source_files:
                add_file(
                    archive,
                    root_name,
                    source,
                    relative,
                    manifest_files,
                    progress,
                )
                completed = progress["files"]
                if completed - last_report >= 1000:
                    last_report = completed
                    print(
                        "Packed %s files, %.2f GiB"
                        % (completed, progress["bytes"] / (1024 ** 3)),
                        flush=True,
                    )

            for relative, data in sorted(body_overrides.items()):
                if relative in skip_paths:
                    content, redactions = redact_known_ids(relative, data)
                    progress["redactedIds"] += redactions
                else:
                    content = data
                add_bytes(
                    archive,
                    root_name,
                    relative,
                    content,
                    manifest_files,
                )
                progress["files"] += 1
                progress["bytes"] += len(content)

            report = dict(build_info)
            report.update({
                "actualFiles": len(manifest_files) + 3,
                "actualBytes": progress["bytes"],
                "sourceFiles": len(source_files),
                "overrideFiles": len(body_overrides),
                "knownIdOccurrencesRedacted": progress["redactedIds"],
                "knownIdFilesRedacted": progress["redactedFiles"],
                "formalSavesIncluded": False,
                "browserCacheIncluded": False,
                "logsIncluded": False,
                "snapshotsIncluded": False,
            })
            add_bytes(
                archive,
                root_name,
                report_relative,
                json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
                manifest_files,
            )
            add_bytes(
                archive,
                root_name,
                readme_relative,
                readme,
                manifest_files,
            )
            manifest = {
                "files": sorted(manifest_files, key=lambda row: row["path"])
            }
            add_bytes(
                archive,
                root_name,
                "reports/files.json",
                json.dumps(manifest, indent=2).encode("utf-8"),
                [],
            )
    finally:
        file_handle.close()

    archive_size = output.stat().st_size
    digest = zip_digest.hexdigest()
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(
        "%s  %s\n" % (digest, output.name),
        encoding="ascii",
    )

    with zipfile.ZipFile(output, "r") as archive:
        names = archive.namelist()
        forbidden = [
            name for name in names
            if (
                "/data/" in name
                and not name.endswith("/data/native/")
                and not name.endswith("/data/page/")
                and not name.endswith("/data/state/")
            )
            or "/logs/" in name and not name.endswith("/logs/")
            or "/snapshots/" in name and not name.endswith("/snapshots/")
            or "/run/" in name and not name.endswith("/run/")
            or name.endswith((".sqlite", ".sqlite3", ".db", ".log", ".lnk"))
            or name.endswith("/PROGRESS.md")
        ]
        if forbidden:
            raise RuntimeError("Forbidden archive entry: " + forbidden[0])
        known_pattern = re.compile(
            b"|".join(re.escape(value.encode("ascii"))
                      for value in KNOWN_ACCOUNT_IDS)
        )
        for name in names:
            if name.endswith("/"):
                continue
            data = archive.read(name)
            if known_pattern.search(data):
                raise RuntimeError("Known account identifier found in " + name)

    print(json.dumps({
        "zip": str(output),
        "sha256": digest,
        "bytes": archive_size,
        "files": progress["files"] + 3,
        "checksumFile": str(checksum),
        "accountDataIncluded": False,
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
