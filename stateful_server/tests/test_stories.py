from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from cgls.app import create_app
from cgls.stories import StoryService


ROOT = Path(__file__).resolve().parents[1]


class StoryTests(unittest.TestCase):
    def test_reward_once_concurrent_retry_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'state.sqlite'
            app = create_app(db, ROOT / 'fixtures/gacha_1005.json')
            client = TestClient(app)
            before = client.get('/api/local/state').json()['freeSakuradite']
            service = StoryService(app.state.session_factory, app.state.starter_profile)
            quest = next(q for q in service.quests.values() if q.get('onlyStory') and q.get('rewardOnlyStory') == 50)
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(service.complete, [quest['questId']] * 8))
            self.assertTrue(all(r['userQuestList'][0]['questStatus'] == 'CLEARED' for r in results))
            self.assertEqual(client.get('/api/local/state').json()['freeSakuradite'], before + 50)
            app.state.engine.dispose()
            reopened = create_app(db, ROOT / 'fixtures/gacha_1005.json')
            again = TestClient(reopened)
            response = again.post('/api/quest/story/end', json={'questId': quest['questId']})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(again.get('/api/local/state').json()['freeSakuradite'], before + 50)
            rows = again.get('/api/local/page-state').json()['userStoryList']
            self.assertTrue(any(q['questId'] == quest['questId'] and q['questStatus'] == 'CLEARED' for q in rows))
            for payload, status in [({'questId': -1}, 400), ({'questId': 512001}, 400),
                                    ({'questId': True}, 422), ({'questId': quest['questId'], 'reward': 9999}, 422)]:
                self.assertEqual(again.post('/api/quest/story/end', json=payload).status_code, status)
            self.assertEqual(again.get('/api/local/state').json()['freeSakuradite'], before + 50)
            reopened.state.engine.dispose()


if __name__ == '__main__':
    unittest.main()
