import tempfile
import unittest
from pathlib import Path

from deck_store import DeckStore, DeckStoreError


SEED = [
    {
        "deckType": "MULTI_FRONT",
        "createdAt": "2026-10-18T19:00:00+09:00",
    },
    {
        "deckType": "MAIN1",
        "createdAt": "2026-10-18T19:00:01+09:00",
        "userCardId1": "card-a",
        "userKnightmareFrameId1": "kmf-a",
    },
    {
        "deckType": "ARENA",
        "createdAt": "2026-10-18T19:00:02+09:00",
    },
]

MODELS = {
    "gameUser": {"name": "local"},
    "userCardList": [
        {"userCardId": "card-a", "cardId": 101001},
        {"userCardId": "card-b", "cardId": 101002},
    ],
    "userKnightmareFrameList": [
        {"userKnightmareFrameId": "kmf-a", "knightmareFrameId": 2001},
        {"userKnightmareFrameId": "kmf-b", "knightmareFrameId": 2002},
    ],
    "cardList": [
        {"cardId": 101001, "name": "A"},
        {"cardId": 101002, "name": "B"},
        {"cardId": 999999, "name": "Unowned"},
    ],
    "knightmareFrameList": [
        {"knightmareFrameId": 2001, "name": "KMF A"},
        {"knightmareFrameId": 2002, "name": "KMF B"},
    ],
    "userKnightmareFrameCustomizeList": [],
    "userCharaList": [],
    "userItemList": [],
    "userStatusList": [],
    "itemList": [],
    "charaList": [],
    "knightmareFrameCustomizeList": [],
    "eventList": [],
    "campaignList": [],
    "viewIconList": [],
    "backgroundGroupList": [],
    "userBackgroundGroupList": [],
}


class DeckStoreTests(unittest.TestCase):
    def test_official_batch_is_atomic_clear_and_rename_persist(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'decks.sqlite'
            store = DeckStore(path, SEED)
            original = store.list('account')
            first = {'deckType': 'MAIN1', 'userCardIdList': ['card-b'],
                     'userKnightmareFrameIdList': ['kmf-b']}
            invalid = {'deckType': 'ARENA', 'userCardIdList': ['foreign'],
                       'userKnightmareFrameIdList': ['kmf-a']}
            with self.assertRaises(DeckStoreError):
                store.save_many('account', [first, invalid], {'card-a', 'card-b'}, {'kmf-a', 'kmf-b'})
            self.assertEqual(store.list('account'), original)
            store.save_many('account', [first], {'card-a', 'card-b'}, {'kmf-a', 'kmf-b'})
            store.rename('account', 'MAIN1', 'Test team')
            again = DeckStore(path, SEED)
            self.assertEqual(again.list('account')[1]['name'], 'Test team')
            self.assertEqual(again.list('account')[1]['slots'][0]['userCardId'], 'card-b')
            again.save_many('account', [{'deckType': 'MAIN1', 'userCardIdList': [], 'userKnightmareFrameIdList': []}])
            self.assertEqual(again.list('account')[1]['slots'], [])

    def test_seed_save_and_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "decks.sqlite"
            store = DeckStore(path, SEED)
            decks = store.list("account")
            self.assertEqual(
                [deck["deckType"] for deck in decks],
                ["MULTI_FRONT", "MAIN1", "ARENA"],
            )
            self.assertEqual(decks[1]["slots"][0], {
                "userCardId": "card-a",
                "userKnightmareFrameId": "kmf-a",
            })

            saved = store.save(
                "account",
                "MAIN1",
                [
                    {"userCardId": "card-a", "userKnightmareFrameId": "kmf-a"},
                    {"userCardId": "card-b", "userKnightmareFrameId": "kmf-b"},
                ],
                name="Main",
                owned_cards={"card-a", "card-b"},
                owned_kmfs={"kmf-a", "kmf-b"},
            )
            self.assertEqual(saved["name"], "Main")
            self.assertEqual(len(saved["slots"]), 2)

            reopened = DeckStore(path, SEED)
            deck = reopened.list("account")[1]
            self.assertEqual(deck["name"], "Main")
            self.assertEqual(deck["slots"][1]["userCardId"], "card-b")

    def test_rejects_duplicate_missing_and_unowned_members(self):
        with tempfile.TemporaryDirectory() as root:
            store = DeckStore(Path(root) / "decks.sqlite", SEED)
            with self.assertRaises(DeckStoreError):
                store.save(
                    "account",
                    "MAIN1",
                    [
                        {"userCardId": "card-a", "userKnightmareFrameId": "kmf-a"},
                        {"userCardId": "card-a", "userKnightmareFrameId": "kmf-b"},
                    ],
                )
            with self.assertRaises(DeckStoreError):
                store.save(
                    "account",
                    "MAIN1",
                    [{"userCardId": "card-a"}],
                )
            with self.assertRaises(DeckStoreError):
                store.save(
                    "account",
                    "MAIN1",
                    [{"userCardId": "card-x", "userKnightmareFrameId": "kmf-a"}],
                    owned_cards={"card-a"},
                    owned_kmfs={"kmf-a"},
                )
            self.assertEqual(store.list("account")[1]["name"], None)

    def test_page_payload_filters_definitions_to_owned_units(self):
        with tempfile.TemporaryDirectory() as root:
            store = DeckStore(Path(root) / "decks.sqlite", SEED)
            payload = store.page_payload("account", MODELS)
            self.assertEqual(payload["resultCode"], "success")
            self.assertEqual(payload["gameUser"]["name"], "local")
            self.assertEqual(payload["userDeckList"][1]["userCardId1"], "card-a")
            self.assertEqual(
                [card["cardId"] for card in payload["cardList"]],
                [101001, 101002],
            )
            self.assertEqual(
                [kmf["knightmareFrameId"] for kmf in payload["knightmareFrameList"]],
                [2001, 2002],
            )

    def test_reconcile_foreign_capture_preserves_owned_slots_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            store = DeckStore(Path(root) / "decks.sqlite", SEED)
            store.save("local", "MAIN1", [
                {"userCardId": "foreign", "userKnightmareFrameId": "foreign"},
                {"userCardId": "card-b", "userKnightmareFrameId": "kmf-b"}])
            store.reconcile_ownership("local", MODELS)
            first = store.list("local")
            self.assertIsNone(first[1]["slots"][0])
            self.assertEqual(first[1]["slots"][1]["userCardId"], "card-b")
            store.reconcile_ownership("local", MODELS)
            self.assertEqual(first, store.list("local"))

    def test_shared_models_are_not_replaced_with_editor_stubs(self):
        import copy
        models = copy.deepcopy(MODELS)
        models["userCardList"][0]["hp"] = 1234
        models["userCardList"][0]["bondsPoint"] = 50
        models["cardList"][0]["cardSkill1"] = {"id": 42}
        models["userItemList"] = [{"itemId": "GOLD", "quantity": 1000}]
        with tempfile.TemporaryDirectory() as root:
            store = DeckStore(Path(root) / "decks.sqlite", SEED)
            payload = store.page_payload("local", models)
            self.assertEqual(payload["userCardList"][0]["hp"], 1234)
            self.assertEqual(payload["cardList"][0]["cardSkill1"], {"id": 42})
            self.assertEqual(payload["userItemList"], models["userItemList"])


if __name__ == "__main__":
    unittest.main()
