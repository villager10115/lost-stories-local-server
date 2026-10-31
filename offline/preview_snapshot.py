"""Read-only browser preview policy; never persists changes to saved progress."""
import json
import hashlib
from pathlib import Path
from web_audit import decode_text
from snapshot_store import SnapshotStore

class PreviewSnapshotStore(SnapshotStore):
    def __init__(self, root, user_source=None):
        super().__init__(root)
        data = json.loads(self.payload)
        self.user_source = None
        if user_source is not None:
            raw = Path(user_source).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if Path(user_source).name != digest + ".body":
                raise ValueError("User source checksum mismatch")
            supplement = json.loads(decode_text(raw)[0])
            user = supplement.get("user")
            identity = data["gameUser"].get("userId", data["gameUser"].get("id"))
            if not isinstance(user, dict) or identity is None or str(user.get("id")) != str(identity):
                raise ValueError("User source account mismatch")
            if "user" in data:
                raise ValueError("Refusing to replace existing user")
            data["user"] = user
            self.user_source = {"sha256": digest, "time": supplement.get("currentTime"),
                                "mode": "explicit preview supplement; not a complete save"}
        self.omissions = {}
        for key in ("gachaAdvList", "birthdayItemId", "charaBirthdayLoginBonusList",
                    "receivedLoginBonusCampaignLotteryList", "loginBonusComebackList",
                    "loginBonusStartDashList", "loginBonusCampaignList", "loginBonusList"):
            if key in data:
                self.omissions[key] = len(data[key]) if isinstance(data[key], list) else 1
                del data[key]  # Empty arrays are truthy in the cached JavaScript.
        self.payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
