"""Stage standalone native catalogs for loopback resources; never patch or launch a client."""
import argparse
import hashlib
import json
import re
from pathlib import Path

TOKEN = "{Zero.Config.Environment.URL}"


def rewrite_catalog(catalog, port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid loopback port")
    result = json.loads(json.dumps(catalog))
    changed = 0
    for field in ("m_InternalIds", "m_InternalIdPrefixes"):
        values = result.get(field)
        if values is None:
            continue
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError("Invalid internal ID table")
        for index, value in enumerate(values):
            if TOKEN in value:
                if not value.startswith(TOKEN + "/"):
                    raise ValueError("Unexpected resource URL token position")
                values[index] = value.replace(TOKEN, f"http://127.0.0.1:{port}/assets", 1)
                changed += 1
            elif re.match(r"^https?://", value, re.I):
                raise ValueError("Unmapped network internal ID")
    if not changed:
        raise ValueError("No resource URL references rewritten")
    return result, changed


def local_settings(settings):
    result = json.loads(json.dumps(settings))
    locations = [v for v in result["m_CatalogLocations"]
                 if "AddressablesMainContentCatalog" in v.get("m_Keys", [])]
    if len(locations) != 1:
        raise ValueError("Expected exactly one main catalog")
    main = locations[0]
    if main["m_InternalId"] != "{UnityEngine.AddressableAssets.Addressables.RuntimePath}/catalog.json":
        raise ValueError("Unexpected main catalog path")
    main["m_Dependencies"] = []
    result["m_CatalogLocations"] = [main]
    result["m_DisableCatalogUpdateOnStart"] = True
    return result


def stage(catalog_dir, settings_path, output, port):
    # Validate everything before creating output. Existing directories are never overwritten.
    payloads, manifest = {}, {"port": port, "sources": [], "limitations": [
        "Not a network sandbox. Application APIs, telemetry and later catalog updates are not redirected.",
        "No client launched. Native compatibility and Unity Hash128 remain unverified."
    ]}
    for name in ("catalog.json", "Binary_catalog.json", "Json_catalog.json"):
        source = catalog_dir / name
        raw = source.read_bytes()
        catalog, count = rewrite_catalog(json.loads(raw.decode("utf-8-sig")), port)
        payloads[name] = catalog
        manifest["sources"].append({"name": name, "source_sha256": hashlib.sha256(raw).hexdigest(),
                                    "rewritten_references": count})
    raw = settings_path.read_bytes()
    payloads["settings.json"] = local_settings(json.loads(raw.decode("utf-8-sig")))
    manifest["settings_source_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["outputs"] = {}
    encoded = {}
    for name, value in payloads.items():
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded[name] = body
        manifest["outputs"][name] = hashlib.sha256(body).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    for name, body in encoded.items():
        (output / name).write_bytes(body)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    stage(args.catalog_dir, args.settings, args.output, args.port)
