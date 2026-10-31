"""Build dedicated Sandbox input and an automatic isolated launcher."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
from sandbox_config import configuration
from isolated_server import ExecutableStore
from snapshot_store import SnapshotStore

def prepare(web, snapshot, output, entry, version):
    ExecutableStore(web, entry, version)
    SnapshotStore(snapshot)
    output = Path(output).resolve()
    if output.with_suffix(".wsb").exists():
        raise FileExistsError("Configuration already exists")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(web, output / "web")
    shutil.copytree(snapshot, output / "snapshot")
    app = output / "app"
    app.mkdir()
    for name in ("isolated_server.py", "static_server.py", "snapshot_store.py",
                 "web_audit.py", "account_store.py", "account_page.py",
                 "native_bridge.js", "bridge_binding.js"):
        shutil.copy2(Path(__file__).parent / name, app / name)
    runtime = output / "python"
    runtime.mkdir()
    base = Path(sys.base_prefix)
    for pattern in ("python.exe", "python3*.dll", "vcruntime*.dll"):
        for file in base.glob(pattern):
            shutil.copy2(file, runtime / file.name)
    for name in ("DLLs", "Lib"):
        shutil.copytree(base / name, runtime / name,
                        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests", "idlelib"))
    import brotli
    import _brotli
    shutil.copy2(brotli.__file__, runtime / "Lib" / Path(brotli.__file__).name)
    shutil.copy2(_brotli.__file__, runtime / "DLLs" / Path(_brotli.__file__).name)
    (output / "launch.json").write_text(json.dumps(dict(entry=entry, version=version)), encoding="utf-8")
    shutil.copy2(Path(__file__).parent / "sandbox_start.ps1", output / "start.ps1")
    root = ET.fromstring(configuration(output))
    logon = ET.SubElement(root, "LogonCommand")
    ET.SubElement(logon, "Command").text = (
        r'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\OfflineInput\start.ps1')
    wsb = output.with_suffix(".wsb")
    with wsb.open("x", encoding="utf-8") as target:
        target.write(ET.tostring(root, encoding="unicode"))
    return wsb

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("web", type=Path)
    p.add_argument("snapshot", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--entry", required=True)
    p.add_argument("--app-version", required=True)
    a = p.parse_args()
    print(prepare(a.web, a.snapshot, a.output, a.entry, a.app_version))
