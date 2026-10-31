"""Extract static battle definitions only; never import captured player state."""
import hashlib
import json
from pathlib import Path
from extract_main_story_catalog import extract_catalog

ROOT = Path('D:/codegeass')
CAPTURE = Path('D:/LostStories_Preservation_20261018/official-capture-20261019-115638/decoded-final')
start_path = next(CAPTURE.glob('bodies___api_battle_start*'))
end_path = next(CAPTURE.glob('bodies___api_battle_end*'))
start = json.loads(start_path.read_text('utf8'))
end = json.loads(end_path.read_text('utf8'))
quest = start['battle']['questData']
rewards = dict(zip(end['battleResult']['dropIdList'], end['battleResult']['rewardList']))
drop_rewards = {}
for wave in quest['waveData']:
    for index, event in enumerate(wave['waveEventData']):
        old = event.pop('dropId', None)
        if old:
            key = 'spawn-%s' % index
            event['dropId'] = key
            reward = dict(rewards[old])
            # Capture is Monday: this daily type's official coefficient is 2.
            assert reward['num'] % 2 == 0
            reward['num'] //= 2
            drop_rewards[key] = reward
fixture = {
    'sources': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (start_path, end_path)},
    'rewardPolicy': 'Local fixed captured drop schedule, normalized before weekday bonus; official lottery probabilities are not reconstructed.',
    'quest': end['userQuestList'][0]['quest'], 'questData': quest,
    'dropRewards': drop_rewards, 'affiliationData': start['battle']['affiliationData'],
}
(ROOT / 'stateful_server/fixtures/battle_512001.json').write_text(
    json.dumps(fixture, ensure_ascii=False, indent=2), encoding='utf8')
locations_path = next(Path('D:/LostStories_Preservation_20261018/battle-capture-20261019-123013/decoded').glob('bodies___api_page_MainStoryTop*'))
main = extract_catalog(ROOT / 'snapshots/main-story-full-scan-20261021.json', locations_path)
(ROOT / 'stateful_server/fixtures/main_story_catalog.json').write_text(
    json.dumps(main, ensure_ascii=False, indent=2), encoding='utf8')
print('Extracted one battle and all preserved main chapters; no captured account state.')
