"""Apply the narrow repair to source or a copied package app tree."""
from pathlib import Path
import shutil
import sys


def replace(path, before, after):
    value = path.read_text(encoding='utf8')
    if after in value:
        return
    if value.count(before) != 1:
        raise ValueError(f'Expected exactly one repair anchor: {path}: {before[:60]}')
    path.write_text(value.replace(before, after, 1), encoding='utf8')


def patch(root):
    root = Path(root)
    deck = root / 'offline/deck_store.py'
    replace(deck, 'from contextlib import closing', 'from contextlib import closing, nullcontext')
    replace(deck, 'owned_cards=None, owned_kmfs=None):',
            'owned_cards=None, owned_kmfs=None, *, _db=None, allow_empty=False):')
    replace(deck, 'not 1 <= len(slots) <= MAX_DECK_SLOTS',
            'not (0 if allow_empty else 1) <= len(slots) <= MAX_DECK_SLOTS')
    replace(deck, 'if not filled:\n            raise DeckStoreError("Deck cannot be empty")',
            'if not filled and not allow_empty:\n            raise DeckStoreError("Deck cannot be empty")')
    replace(deck, 'with self._transaction() as db:\n            self._ensure_seeded(db, account)\n            current = db.execute(',
            'with (self._transaction() if _db is None else nullcontext(_db)) as db:\n            self._ensure_seeded(db, account)\n            current = db.execute(')
    marker = '    def page_payload(self, account, account_models, extra_user_cards=(),'
    methods = '''    def save_many(self, account, requests, owned_cards=None, owned_kmfs=None):
        if not isinstance(requests, list) or not 1 <= len(requests) <= len(self.seed_order):
            raise DeckStoreError("Expected a bounded deck list")
        result, seen = [], set()
        with self._transaction() as db:
            for request in requests:
                if not isinstance(request, dict):
                    raise DeckStoreError("Expected deck object")
                kind = request.get("deckType")
                if not isinstance(kind, str) or kind in seen:
                    raise DeckStoreError("Invalid or duplicate deck type")
                seen.add(kind)
                slots = request.get("slots")
                official = "userCardIdList" in request or "userKnightmareFrameIdList" in request
                if official:
                    cards, kmfs = request.get("userCardIdList"), request.get("userKnightmareFrameIdList")
                    if ("slots" in request or not isinstance(cards, list) or not isinstance(kmfs, list)
                            or len(cards) != len(kmfs) or len(cards) > MAX_DECK_SLOTS):
                        raise DeckStoreError("Expected paired pilot/KMF arrays")
                    slots = [None if c in (None, "") and k in (None, "") else
                             {"userCardId": c, "userKnightmareFrameId": k} for c, k in zip(cards, kmfs)]
                result.append(self.save(account, kind, slots, request.get("name"),
                                        owned_cards, owned_kmfs, _db=db, allow_empty=official))
        return result

    def rename(self, account, deck_type, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 10:
            raise DeckStoreError("Deck name must contain 1-10 characters")
        if not isinstance(deck_type, str) or deck_type not in self.seed_order:
            raise DeckStoreError("Unknown deck type")
        with self._transaction() as db:
            self._ensure_seeded(db, account)
            row = db.execute("SELECT slots_json, created_at FROM local_decks WHERE account=? AND deck_type=?",
                             (account, deck_type)).fetchone()
            if row is None:
                raise DeckStoreError("Deck does not exist")
            db.execute("UPDATE local_decks SET name=?, updated_at=? WHERE account=? AND deck_type=?",
                       (name.strip(), datetime.now(JST).isoformat(), account, deck_type))
        return {"deckType": deck_type, "name": name.strip(), "slots": json.loads(row[0]), "createdAt": row[1]}

'''
    replace(deck, marker, methods + marker)
    replace(deck, '        return payload\n', '''        # Preserve the full shared model required by the original card/KMF UI.
        full = copy.deepcopy(account_models)
        full.update(payload)
        for key in ("user", "affiliationList", "costumeList", "userCostumeList",
                    "userQuestList", "userCardAttributeRankList", "naviDeckList",
                    "naviDeckCardList", "naviDeckKnightmareFrameCustomizeList"):
            full[key] = copy.deepcopy(account_models.get(key, {} if key == "user" else []))
        return full
''')
    server = root / 'offline/server.py'
    replace(server, '            length = int(lengths[0])\n            if not 0 < length <= 4096:',
            '            length = int(lengths[0])\n            limit = 32768 if bootstrap_path == "/api/deck/saveList" else 4096\n            if not 0 < length <= limit:')
    anchor = '        if self.path.split("?", 1)[0] == "/api/deck/save":'
    replace(server, anchor, '''        from formation_routes import handle as handle_formation
        if handle_formation(self, bootstrap_path, raw_body):
            return
''' + anchor)
    replace(server, '        self.respond(status, body, content_type)\n\n\ndef main():', '''        if status == 200 and target_path == "/api/quest/story/end":
            result = json.loads(body)
            models = self.server.account_models()
            for key in ("gameUser", "userItemList", "userStatusList"):
                result[key] = models.get(key, {} if key == "gameUser" else [])
            body = json.dumps(result, ensure_ascii=False).encode("utf8")
        self.respond(status, body, content_type)


def main():''')
    app = root / 'stateful_server/cgls/app.py'
    replace(app, '    app.state.starter_profile = profile', '''    app.state.starter_profile = profile
    from .stories import install_routes as install_story_routes, story_state
    install_story_routes(app, session_factory, profile)''')
    replace(app, '            **mission_state,', '''            **mission_state,
            "userStoryList": story_state(session, user.id),''')
    page = root / 'offline/new_account_page.py'
    replace(page, '        for quest in self.main_story_catalog["quests"]:', '''        progress.update({row["questId"]: row for row in (state or {}).get("userStoryList", [])})
        for quest in self.main_story_catalog["quests"]:''')


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
