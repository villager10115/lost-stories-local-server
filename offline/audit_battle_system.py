"""Read-only package audit; does not launch the game or alter formal saves."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def audit(root, output, decode_maps=False):
    root, output = Path(root), Path(output)
    config = json.loads((root / 'config/private-server.json').read_text('utf8'))
    sys.path.insert(0, str(root / 'app/offline'))
    from web_store import WebStore
    from preserved_web import PreservedWebStore
    web = WebStore(root / config['webRoot'], config['webEntry'])
    preserved = PreservedWebStore(root / config['preservedPages'])

    def resolve(path):
        reply = web.resolve(path)
        return reply if reply[0] == 200 else preserved.resolve(path)

    rows = json.loads((root / config['assetMapping']).read_text('utf8'))
    index = {r['id'].split('}/')[-1].lower(): r for r in rows}
    cache = root / config['assetCache']
    quests = json.loads((root / 'app/stateful_server/fixtures/main_story_catalog.json').read_text('utf8'))['quests']
    battles = [q for q in quests if not q.get('onlyStory')]
    maps = sorted({q['mapDataNo'] for q in battles})
    fields = sorted({q['fieldId'] for q in battles})
    # Master field.assetNo maps to native FieldData.assetId; the client prefers
    # assetId over fieldId. Do not report valid scene aliases as missing files.
    field_assets = {q['fieldId']: int(q.get('field', {}).get('assetNo') or q['fieldId'])
                    for q in battles}

    def check(selected):
        failures = []
        for row in selected:
            opts = row['options']
            identity = opts['m_BundleName'] + '_' + opts['m_Hash']
            path = cache / identity
            if not path.is_file() or path.stat().st_size != opts['m_BundleSize']:
                failures.append({'resource': row['id'], 'identity': identity})
        return {'catalogEntries': len(selected), 'identitySizeFailures': failures,
                'payloadHashVerification': False}

    refs = []
    for number in maps:
        refs.append('data_assets_data/mapdata/battlemapdata_%s.bundle' % number)
    for number in sorted(set(field_assets.values())):
        refs.append('scene_scenes_backgrounds/battlefields/fields/fie_%s/fie_%s.bundle' % (number, number))
    unlocated = [p for p in refs if p not in index]
    groups = {}
    for name, predicate in {
        'mapData': lambda p: '/mapdata/battlemapdata_' in p,
        'battleFields': lambda p: 'battlefields' in p,
        'knightmare': lambda p: 'knightmare' in p,
        'effects': lambda p: 'effect' in p,
        'live2d': lambda p: 'live2d' in p,
        'mainAdventure': lambda p: '/adv/main/' in p,
    }.items():
        groups[name] = check([r for r in rows if predicate(r['id'].lower())])

    decoded = []
    if decode_maps:
        import UnityPy
        for number in maps:
            key = 'data_assets_data/mapdata/battlemapdata_%s.bundle' % number
            if key not in index:
                continue
            opts = index[key]['options']
            path = cache / (opts['m_BundleName'] + '_' + opts['m_Hash'])
            entry = {'mapDataNo': number}
            try:
                objects = UnityPy.load(str(path)).objects
                found = []
                for obj in objects:
                    if obj.type.name != 'MonoBehaviour':
                        continue
                    tree = obj.read_typetree()
                    if '_serializeData' in tree:
                        data = tree['_serializeData']
                        found.append({'name': tree.get('m_Name'),
                            'fields': sorted(data),
                            'panels': len(data.get('battleMapPanelDatas', [])),
                            'mapSizeType': data.get('mapSizeType')})
                entry.update(ok=bool(found), maps=found, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            except Exception as exc:
                entry.update(ok=False, error=str(exc))
            decoded.append(entry)
            if len(decoded) % 100 == 0:
                print('Decoded maps:', len(decoded), flush=True)

    paths = ['/web/js/quest/QuestBackground.js', '/web/js/quest/QuestResult.js']
    dependencies = {}
    api_names, commands = set(), set()
    for path in paths:
        status, body, _ = resolve(path)
        dependencies[path] = {'status': status, 'sha256': hashlib.sha256(body).hexdigest()}
        if status != 200:
            continue
        script = body.decode('utf8')
        api_names.update(re.findall(r'linkList\.([A-Za-z0-9_]+)', script))
        commands.update(re.findall(r'\b[a-z]\.((?:push|pop|hide|show|remove|set)[A-Z][A-Za-z]+)\(', script))
        match = re.search(r'define\(\s*\[([^]]+)\]', script)
        for dep in re.findall(r'"text!([^"]+)"', match[1] if match else ''):
            key = '/web/' + dep
            status, body, _ = resolve(key)
            dependencies[key] = {'status': status, 'sha256': hashlib.sha256(body).hexdigest()}

    source = root / 'app/stateful_server/cgls/app.py'
    routes = []
    for module in source.parent.glob('*.py'):
        text = module.read_text('utf8')
        routes.extend({'method': m.upper(), 'path': p} for m, p in
            re.findall(r'''@app\.(get|post|put|delete)\(["']([^"']+)["']\)''', text))
    report = {'package': str(root), 'clientBuild': '1.6.11',
        'scope': 'Read-only static resource/protocol audit. Not a native gameplay acceptance test.',
        'mainBattleDefinitions': len(battles), 'mainMapReferences': len(maps),
        'mainFieldReferences': len(fields), 'unlocatedMapOrFieldReferences': unlocated,
        'fieldAssetAliases': {str(k): v for k, v in field_assets.items() if k != v},
        'mainReferencedAssets': check([index[p] for p in refs if p in index]),
        'resourceGroups': groups, 'decodedMaps': decoded,
        'frontendDependencies': dependencies, 'frontendApiNames': sorted(api_names),
        'frontendCommands': sorted(commands),
        'deployedBattleRoutes': [r for r in routes if '/battle' in r['path']],
        'deployedStoryRoutes': [r for r in routes if '/quest/story' in r['path']],
        'mainDefinitionsWithDetailedWaveData': sum(bool(q.get('waveData')) for q in battles),
        'mainDefinitionsWithWaveReferences': sum(bool(q.get('waveIds')) for q in battles),
        'nativeRenderingVerified': False, 'formalSaveMutations': False}
    if decoded:
        manifest = json.loads((root / 'reports/files.json').read_text('utf8'))
        expected = {x['path'].replace('\\', '/'): x['sha256'] for x in manifest['files']}
        failures = []
        for item in decoded:
            row = index['data_assets_data/mapdata/battlemapdata_%s.bundle' % item['mapDataNo']]
            opts = row['options']
            key = 'assets/ResourceCache/' + opts['m_BundleName'] + '_' + opts['m_Hash']
            if not item.get('ok') or expected.get(key) != item.get('sha256'):
                failures.append(item['mapDataNo'])
        report['mapFileManifestVerification'] = {'checked': len(decoded), 'failures': failures}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in report.items() if k not in
        ('decodedMaps', 'frontendDependencies', 'frontendApiNames', 'frontendCommands')}, ensure_ascii=True, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--decode-maps', action='store_true')
    args = parser.parse_args()
    audit(args.root, args.output, args.decode_maps)
