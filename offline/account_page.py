"""MyPage-compatible read adapter backed by the selected local SQLite account."""
import json

from snapshot_store import SnapshotStore


class AccountPage(SnapshotStore):
    """Reuse strict route/query validation, not snapshot file replay."""

    def __init__(self, store, account):
        self.store = store
        self.account = account
        self.store.state(account)

    def page_payload(self):
        # Read a consistent transaction on every request, never merge old responses.
        return json.dumps(self.store.state(self.account), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
