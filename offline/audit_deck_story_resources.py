"""Read-only audit of retained deck UI and story/native resource identities."""
import argparse
import json
from pathlib import Path
import re

from web_store import WebStore
from preserved_web import PreservedWebStore


def audit(root, official_deck):
    root = Path(root)
    config = json.loads((root / 'config/private-server.json').read_text(encoding='utf8'))
    web = WebStore(root / config['webRoot'], config['webEntry'])
    preserved = PreservedWebStore(root / config['preservedPages'])
    def resolve(path):
        result = web.resolve(path)
        return result if result[0] == 200 else preserved.resolve(path)

    official = Path(official_deck).read_text(encoding='utf8')
    queue = ['/web/js/deck/DeckFormation.js']
    dependencies = {}
    while queue:
        path = queue.pop()
        if path in dependencies:
            continue
        status, body = (200, official.encode()) if path == queue_root else resolve(path)[:2]
        dependencies[path] = status
        if status != 200 or not path.endswith('.js'):
            continue
        match = re.search(r'define\(\s*\[([^]]*)\]', body.decode('utf8'))
        if match:
            for dep in re.findall(r'"([^"]+)"', match[1]):
                if dep.startswith('text!'):
                    queue.append('/web/' + dep[5:])
                elif dep.startswith('js/'):
                    queue.append('/web/' + dep + '.js')

    mapping = json.loads((root / config['assetMapping']).read_text(encoding='utf8'))
    cache = root / config['assetCache']
    catalog = json.loads((root / 'app/stateful_server/fixtures/main_story_catalog.json').read_text(encoding='utf8'))
    def check(rows):
        errors = []
        for row in rows:
            options = row['options']
            identity = options['m_BundleName'] + '_' + options['m_Hash']
            target = cache / identity
            if not target.is_file() or target.stat().st_size != options['m_BundleSize']:
                errors.append({'id': row['id'], 'identity': identity})
        return {'entries': len(rows), 'identityAndSizeFailures': errors,
                'payloadHashesChecked': False}

    groups = {}
    for name, predicate in (
        ('live2d', lambda s: 'live2d' in s),
        ('pilotSprites', lambda s: '/sprite_assets_sprites/pilot/' in s),
        ('knightmare', lambda s: 'knightmare' in s),
        ('mainStoryScripts', lambda s: '/json_assets_json/adv/main/' in s),
    ):
        groups[name] = check([row for row in mapping if predicate(row['id'].lower())])
    ids = {row['id'].split('}/', 1)[-1].lower() for row in mapping}
    stories = [q for q in catalog['quests'] if q.get('onlyStory')]
    unlocated = []
    for quest in stories:
        name = quest.get('startStoryNo', '').lower()
        for suffix in ('.bundle', '/' + name + '_command.bundle', '/' + name + '_voice.bundle'):
            resource = 'json_assets_json/adv/main/' + name + suffix
            if resource not in ids:
                unlocated.append({'questId': quest['questId'], 'resource': resource})
    deployed = resolve(queue_root)[1].decode('utf8')
    report = {
        'deckDependencies': dependencies,
        'dependencyScope': 'Explicit js/ and text! AMD dependencies; global aliases and dynamic image paths excluded',
        'deployedSimplifiedDeck': 'deckPilotSelect' in deployed,
        'deployedQuestDelegation': 'LocalBattleDeck' in deployed,
        'officialDeckApiNames': sorted(set(re.findall(r'linkList\.([A-Za-z0-9_]+)', official))),
        'nativeResourceGroups': groups,
        'storyOnlyQuests': len(stories),
        'unlocatedStoryReferences': unlocated,
        'storyFailure': {'path': '/api/quest/story/end', 'status': 403,
                         'cause': 'No route handler; request reaches generic token-only fallback before native playback'},
        'nativeRenderingVerified': False,
    }
    return report


queue_root = '/web/js/deck/DeckFormation.js'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('official_deck', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = audit(args.package, args.official_deck)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('deckDependencies', 'unlocatedStoryReferences')}, ensure_ascii=True, indent=2))
    print('Unlocated story references:', len(result['unlocatedStoryReferences']))
