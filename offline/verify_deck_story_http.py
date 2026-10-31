"""Exercise deployed-candidate routes on consistent copies of formal saves."""
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import threading
import time
import urllib.request
import urllib.error

import uvicorn


def run(package, source, output):
    sys.path[:0] = [str(source / 'offline'), str(source / 'stateful_server')]
    from server import LocalServer
    from cgls.app import create_app
    output.mkdir(parents=True, exist_ok=True)
    for rel, name in [('data/state/state.sqlite', 'state.sqlite'), ('data/page/decks.sqlite', 'decks.sqlite'),
                      ('data/page/prototype.sqlite', 'page.sqlite')]:
        with sqlite3.connect((package / rel).as_uri() + '?mode=ro', uri=True) as a, sqlite3.connect(output / name) as b:
            a.backup(b)
            assert b.execute('pragma integrity_check').fetchone()[0] == 'ok'
    report = {}
    for iteration in range(2):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        app = create_app(output / 'state.sqlite', source / 'stateful_server/fixtures/gacha_1005.json')
        state = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
        thread = threading.Thread(target=state.run, daemon=True)
        thread.start()
        page = None
        try:
            deadline = time.monotonic() + 20
            while not state.started and time.monotonic() < deadline:
                time.sleep(.05)
            assert state.started
            state_url = f'http://127.0.0.1:{port}'
            page = LocalServer(0, output / 'page.sqlite', deck_database=output / 'decks.sqlite',
                               masterdata=package / 'assets/masterdata', gacha_upstream=state_url,
                               gacha_state_url=state_url + '/api/local/page-state')
            page_thread = threading.Thread(target=page.serve_forever, daemon=True)
            page_thread.start()
            def request(path, body=None, session=True, expected=200):
                headers = {'Content-Type': 'application/json'}
                if session:
                    headers['X-Web-Session-Id'] = 'candidate-test'
                req = urllib.request.Request('http://' + page.authority + path,
                    data=None if body is None else json.dumps(body).encode(), headers=headers)
                try:
                    response = urllib.request.urlopen(req, timeout=40)
                except urllib.error.HTTPError as exc:
                    response = exc
                assert response.code == expected, (path, response.code, response.read()[:200])
                return json.loads(response.read())
            model = request('/api/page/DeckFormation')
            (output / 'deck-payload.json').write_text(json.dumps(model, ensure_ascii=False), encoding='utf8')
            assert model['affiliationList'] and model['costumeList']
            assert model['userStatusList'] and model['userKnightmareFrameCustomizeList']
            pilot = model['userCardList'][0]['userCardId']
            kmf = model['userKnightmareFrameList'][0]['userKnightmareFrameId']
            quest_model = request('/api/page/MainStoryTop')
            quest = next(q for q in quest_model['userQuestList'] if q['quest'].get('onlyStory') and q['quest']['rewardOnlyStory'] == 50)
            if iteration == 0:
                baseline = next(x['quantity'] for x in model['userItemList'] if x['itemId'] == 'PRESENTED_MONEY')
                request('/api/quest/story/end', {'questId': quest['questId']}, session=False, expected=403)
                result = request('/api/quest/story/end', {'questId': quest['questId']})
                assert result['userQuestList'][0]['questStatus'] == 'CLEARED'
                request('/api/quest/story/end', {'questId': -1}, expected=400)
                request('/api/deck/saveList', {'userDeckInfoList': [
                    {'deckType': 'MAIN1', 'userCardIdList': [pilot], 'userKnightmareFrameIdList': [kmf]},
                    {'deckType': 'MAIN2', 'userCardIdList': [], 'userKnightmareFrameIdList': []}]})
                request('/api/deck/set/name', {'deckType': 'MAIN1', 'name': 'RepairTest'})
            result = request('/api/quest/story/end', {'questId': quest['questId']})
            amount = next(x['quantity'] for x in result['userItemList'] if x['itemId'] == 'PRESENTED_MONEY')
            assert amount == baseline + 50
            assert next(q for q in request('/api/page/MainStoryTop')['userQuestList'] if q['questId'] == quest['questId'])['questStatus'] == 'CLEARED'
            deck = next(d for d in request('/api/page/DeckFormation')['userDeckList'] if d['deckType'] == 'MAIN1')
            assert deck['name'] == 'RepairTest' and deck['userCardId1'] == pilot
            report['initial' if iteration == 0 else 'restart'] = {
                'storyRewardOnce': True, 'storyProgressPersists': True, 'formationPersists': True,
                'ownedPilots': len(model['userCardList']), 'ownedKmfs': len(model['userKnightmareFrameList'])}
        finally:
            if page:
                page.shutdown()
                page.server_close()
                page_thread.join(5)
            state.should_exit = True
            thread.join(10)
            assert not thread.is_alive()
    (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    run(*(Path(x).resolve() for x in sys.argv[1:4]))
