import json
import unittest
from types import SimpleNamespace
from formation_routes import handle


class WeaponSelectionTests(unittest.TestCase):
    def request(self, payload, authenticated=True):
        weapon = {'userKnightmareFrameCustomizeId': 'owned-weapon', 'selected': True}
        models = {'userKnightmareFrameCustomizeList': [weapon], 'userKnightmareFrameList': []}
        response = []
        handler = SimpleNamespace(
            page_session_ok=lambda: authenticated,
            headers={'Content-Type': 'application/json'},
            server=SimpleNamespace(decks=object(), account_models=lambda: models),
            respond=lambda status, data: response.append((status, data)))
        self.assertTrue(handle(handler, '/api/knightmareFrameCustomize/select', json.dumps(payload).encode()))
        return response[0]

    def test_reselecting_owned_weapon_is_idempotent(self):
        request = {'userKnightmareFrameCustomizeId': 'owned-weapon'}
        first = self.request(request)
        self.assertEqual(first[0], 200)
        self.assertEqual(first, self.request(request))

    def test_rejects_foreign_weapon_extra_fields_and_missing_session(self):
        self.assertEqual(self.request({'userKnightmareFrameCustomizeId': 'foreign'})[0], 400)
        self.assertEqual(self.request({'userKnightmareFrameCustomizeId': 'owned-weapon', 'unlock': True})[0], 400)
        self.assertEqual(self.request({'userKnightmareFrameCustomizeId': 'owned-weapon'}, False)[0], 403)


if __name__ == '__main__':
    unittest.main()
