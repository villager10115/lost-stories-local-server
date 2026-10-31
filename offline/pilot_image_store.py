"""Extract pilot artwork from exact cached AssetBundles for the local UI."""

import io
import re
from pathlib import Path

try:
    import UnityPy
except ImportError:  # The server still starts; the image route reports 503.
    UnityPy = None


class PilotImageStore:
    PATTERN = re.compile(
        r"/web/image/pilots/pilot_(\d{6})(?:_(male|female))?_"
        r"(m|square|l|s|full|locket|cutin)\.png"
    )

    def __init__(self, assets):
        self.assets = assets
        self.memory = {}

    @staticmethod
    def bundle_route(card_id, gender, size):
        suffix = "_" + gender if gender else ""
        if size == "cutin":
            return (
                "/assets/sprite_assets_sprites/pilot/image/"
                "pilot_%s%s_cutin.bundle" % (card_id, suffix)
            )
        return (
            "/assets/binary_assets_binary/images/pilots/"
            "pilot_%s%s_%s.bundle" % (card_id, suffix, size)
        )

    def resolve(self, target):
        path = target.split("?", 1)[0]
        match = self.PATTERN.fullmatch(path)
        if not match:
            return 404, b"Unknown pilot image", "text/plain"
        card_id, gender, size = match.groups()
        route = self.bundle_route(card_id, gender, size)
        record = self.assets.routes.get(route)
        if record is None:
            return 404, b"Pilot image bundle is not cached", "text/plain"
        if route in self.memory:
            return 200, self.memory[route], "image/png"
        filename, _size = record
        bundle_path = self.assets.cache / filename
        if UnityPy is None:
            return 503, b"UnityPy is not installed", "text/plain"
        try:
            environment = UnityPy.load(str(bundle_path))
        except Exception:
            return 503, b"Could not read pilot image bundle", "text/plain"
        for obj in environment.objects:
            if obj.type.name != "TextAsset":
                continue
            data = obj.read()
            script = data.m_Script
            body = (
                script.encode("utf-8", "surrogateescape")
                if isinstance(script, str)
                else bytes(script)
            )
            if body.startswith(b"\x89PNG\r\n\x1a\n"):
                self.memory[route] = body
                return 200, body, "image/png"
        if size == "cutin":
            # Cut-in bundles store the transparent character pose as a Sprite,
            # not as a PNG payload in a TextAsset.
            for object_type in ("Sprite", "Texture2D"):
                for obj in environment.objects:
                    if obj.type.name != object_type:
                        continue
                    try:
                        image = obj.read().image
                        output = io.BytesIO()
                        image.save(output, format="PNG")
                    except Exception:
                        continue
                    body = output.getvalue()
                    if body.startswith(b"\x89PNG\r\n\x1a\n"):
                        self.memory[route] = body
                        return 200, body, "image/png"
        return 404, b"Pilot image not found", "text/plain"


__all__ = ["PilotImageStore"]
