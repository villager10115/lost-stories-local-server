"""Read a Chromium blockfile cache snapshot without executing cached content.
Bodies and the manifest can contain personal data; keep the output private.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from urllib.parse import urlsplit, parse_qs


def read_stream(root, address, size):
    if size < 0 or size > 128 * 1024 * 1024:
        raise ValueError("Invalid stream size")
    if not size:
        return b""
    if not address & 0x80000000:
        raise ValueError("Uninitialized address")
    kind = (address >> 28) & 7
    if kind == 0:
        path = root / ("f_%06x" % (address & 0x0fffffff))
        offset = 0
    else:
        sizes = {1: 36, 2: 256, 3: 1024, 4: 4096}
        if kind not in sizes:
            raise ValueError("Unsupported address")
        path = root / ("data_%d" % ((address >> 16) & 255))
        offset = 8192 + (address & 65535) * sizes[kind]
        if size > (((address >> 24) & 3) + 1) * sizes[kind]:
            raise ValueError("Stream exceeds allocated blocks")
    with path.open("rb") as stream:
        stream.seek(offset)
        data = stream.read(size)
    if len(data) != size:
        raise ValueError("Truncated stream")
    return data


def extract(source, output):
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for path in sorted(source.glob("data_*")):
        data = path.read_bytes()
        if len(data) < 8192:
            continue
        # Cache block header: entry_size at offset 12.
        if struct.unpack_from("<I", data, 12)[0] != 256:
            continue
        for pos in range(8192, len(data) - 95, 256):
            state, = struct.unpack_from("<I", data, pos + 20)
            length, long_address = struct.unpack_from("<II", data, pos + 32)
            if state != 0 or not 8 <= length <= 16384:
                continue
            try:
                key = (read_stream(source, long_address, length) if long_address
                       else data[pos + 96:pos + 96 + length])
                if len(key) != length:
                    continue
                key = key.decode("utf-8")
                # Some cache keys have a network isolation prefix.
                start = key.find("http")
                if start < 0:
                    continue
                url = urlsplit(key[start:])
                if url.scheme not in ("http", "https") or not url.hostname:
                    continue
                sizes = struct.unpack_from("<4i", data, pos + 40)
                addresses = struct.unpack_from("<4I", data, pos + 56)
                body = read_stream(source, addresses[1], sizes[1])
                if not body:
                    continue
                digest = hashlib.sha256(body).hexdigest()
                (output / (digest + ".body")).write_bytes(body)
                records.append({"host": url.hostname, "path": url.path,
                                "rev": parse_qs(url.query).get("rev", [None])[0],
                                "bytes": len(body), "sha256": digest,
                                "source_block": path.name + ":" + str(pos)})
            except (ValueError, OSError, UnicodeError):
                continue
    (output / "manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = extract(args.source, args.output)
    print("Extracted entries:", len(result))
    print("Unique bodies:", len({r["sha256"] for r in result}))
