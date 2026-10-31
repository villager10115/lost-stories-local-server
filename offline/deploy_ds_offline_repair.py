"""Deploy and roll back the offline page/startup/battle repair release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess


SOURCE_FILES = (
    ("offline/deploy_ds_offline_repair.py",
     "app/offline/deploy_ds_offline_repair.py"),
    ("offline/server.py", "app/offline/server.py"),
    ("offline/formation_routes.py", "app/offline/formation_routes.py"),
    ("offline/portable_launcher.py", "app/offline/portable_launcher.py"),
    ("offline/portable_launcher.py", "launcher/portable_launcher.py"),
    ("offline/patch_direct_bootstrap.ps1",
     "app/offline/patch_direct_bootstrap.ps1"),
    ("offline/LocalDirectBootstrap.cs",
     "app/offline/LocalDirectBootstrap.cs"),
    ("offline/test_server.py", "app/offline/test_server.py"),
    ("offline/test_account_page.py", "app/offline/test_account_page.py"),
    ("offline/test_account_save_status.py",
     "app/offline/test_account_save_status.py"),
    ("offline/verify_ds_offline_repair.py",
     "app/offline/verify_ds_offline_repair.py"),
    ("stateful_server/cgls/app.py", "app/stateful_server/cgls/app.py"),
    ("stateful_server/cgls/battles.py",
     "app/stateful_server/cgls/battles.py"),
    ("stateful_server/tests/test_battles.py",
     "app/stateful_server/tests/test_battles.py"),
    ("stateful_server/tests/test_shop_system.py",
     "app/stateful_server/tests/test_shop_system.py"),
)

WEB_FILES = (
    "web/template/detail/QuestDetailPopup.html",
    "web/image/common/number/rank_text_number2.webp",
    "web/image/common/number/rank_text_number3.webp",
    "web/image/common/number/rank_text_number4.webp",
    "web/image/common/icon/icon_coloring_s.webp",
    "web/image/common/detail/pnl_itemdetail.webp",
    "web/image/common/detail/pnl_itemdetail_1.webp",
    "web/image/common/detail/pnl_info.webp",
)

DOC_FILES = (
    ("PROGRESS.md", "PROGRESS.md"),
    ("DS_OFFLINE_REPAIR_20261031.md", "DS_OFFLINE_REPAIR_20261031.md"),
    ("DS_OFFLINE_REPAIR_20261031.md",
     "reports/DS_OFFLINE_REPAIR_20261031.md"),
    ("research/ds-offline-repair-20261031.json",
     "research/ds-offline-repair-20261031.json"),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_record(relative, source):
    return {
        "path": relative,
        "bytes": source.stat().st_size,
        "sha256": digest(source),
    }


def collect_pairs(source, package, include_helper):
    pairs = {}
    for source_name, package_name in SOURCE_FILES:
        pairs[package_name] = source / source_name
    for relative in WEB_FILES:
        pairs["assets/static-preview/local_overrides/" + relative] = (
            source / "offline/web_overrides" / relative)
    if include_helper:
        helper = next(package.glob(
            "Client/*_Data/Managed/LocalDirectBootstrap.dll"))
        pairs[helper.relative_to(package).as_posix()] = helper
    return pairs


def ports_closed(package):
    config = json.loads(
        (package / "config/private-server.json").read_text("utf8"))
    for key in ("pagePort", "statePort", "debugPort"):
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", config[key])) == 0:
                return False, key
    return True, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("D:/codegeass"))
    parser.add_argument("--package", type=Path,
                        default=Path("D:/LostStories_Japanese"))
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    package = args.package.resolve()
    backup = args.backup.resolve()
    manifest_path = package / "reports/files.json"
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    index = {row["path"]: row for row in manifest["files"]}

    closed, active_key = ports_closed(package)
    if not closed:
        raise RuntimeError("Local services are active on " + active_key)

    # Compile the already reviewed helper source first, but write it to a
    # disposable sidecar so package preflight still reflects the manifest.
    helper_target = next(package.glob(
        "Client/*_Data/Managed/LocalDirectBootstrap.dll"))
    helper_relative = helper_target.relative_to(package).as_posix()
    helper_old = index.get(helper_relative)
    if helper_old is None or digest(helper_target) != helper_old["sha256"]:
        raise RuntimeError("Installed bootstrap helper changed since manifest")

    pairs = collect_pairs(source, package, include_helper=False)
    missing = [str(path) for path in pairs.values() if not path.is_file()]
    if missing:
        raise RuntimeError("Missing source file: " + missing[0])

    changes = []
    for relative, src in sorted(pairs.items()):
        target = (package / relative).resolve()
        if package not in target.parents:
            raise RuntimeError("Target escaped package: " + relative)
        old = index.get(relative)
        desired = manifest_record(relative, src)
        actual = digest(target) if target.exists() else None
        if target.exists() and old and actual != old["sha256"] and actual != desired["sha256"]:
            raise RuntimeError("Package changed since manifest: " + relative)
        if actual != desired["sha256"]:
            changes.append({
                **desired,
                "oldSha256": actual,
                "source": str(src),
                "target": str(target),
            })

    plan = {
        "package": str(package),
        "backup": str(backup),
        "changes": [{key: row[key] for key in
                     ("path", "bytes", "sha256", "oldSha256")}
                    for row in changes],
        "bootstrapHelperCompile": True,
        "formalDatabaseWrites": False,
        "nativeAssemblyRewritten": False,
    }
    plan_path = source / "snapshots/ds-offline-repair-deployment-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf8")
    if not args.deploy:
        print(json.dumps({
            "plannedWrites": len(changes),
            "plan": str(plan_path),
        }))
        return

    if backup.exists():
        raise RuntimeError("Backup directory already exists")
    backup.mkdir(parents=True)
    (backup / "files.json.before").write_bytes(original_manifest)
    for relative in {
            *(row["path"] for row in changes),
            helper_relative,
    }:
        target = package / relative
        if target.exists():
            saved = backup / "files" / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)

    written = []
    helper_before = helper_target.read_bytes()
    try:
        for row in changes:
            target = Path(row["target"])
            temporary = target.with_name(target.name + ".ds-repair-tmp")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(row["source"], temporary)
            os.replace(temporary, target)
            if digest(target) != row["sha256"]:
                raise RuntimeError("Post-write hash mismatch: " + row["path"])
            written.append(row)
            index[row["path"]] = {
                key: row[key] for key in ("path", "bytes", "sha256")
            }

        patch_script = package / "app/offline/patch_direct_bootstrap.ps1"
        powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not powershell:
            raise RuntimeError("PowerShell was not found")
        completed = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(patch_script), "-Root", str(package)],
            capture_output=True, text=True, timeout=180,
        )
        if completed.returncode:
            raise RuntimeError(
                "Bootstrap helper compile failed: " + completed.stdout +
                completed.stderr)
        helper_record = manifest_record(helper_relative, helper_target)
        helper_record["oldSha256"] = helper_old["sha256"]
        index[helper_relative] = {
            key: helper_record[key] for key in ("path", "bytes", "sha256")
        }

        for source_name, package_name in DOC_FILES:
            src = source / source_name
            target = package / package_name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)

        manifest["files"] = sorted(index.values(), key=lambda row: row["path"])
        temporary = manifest_path.with_suffix(".ds-repair-tmp")
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf8")
        os.replace(temporary, manifest_path)
    except BaseException:
        helper_target.write_bytes(helper_before)
        for row in reversed(written):
            target = Path(row["target"])
            if row["oldSha256"] is None:
                if target.exists():
                    target.unlink()
            else:
                saved = backup / "files" / row["path"]
                shutil.copy2(saved, target)
        manifest_path.write_bytes(original_manifest)
        raise

    plan["helper"] = manifest_record(helper_relative, helper_target)
    plan["manifestEntries"] = len(index)
    (backup / "deployment.json").write_text(
        json.dumps(plan, indent=2), encoding="utf8")
    (package / "reports/ds-offline-repair-deployment.json").write_text(
        json.dumps(plan, indent=2), encoding="utf8")
    print(json.dumps({
        "writes": len(written),
        "helper": plan["helper"],
        "manifestEntries": len(index),
        "backup": str(backup),
    }))


if __name__ == "__main__":
    main()
