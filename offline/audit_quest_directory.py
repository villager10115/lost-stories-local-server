"""Read-only audit of QuestTop and every static/conditional sibling entry."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

from web_store import WebStore
from preserved_web import PreservedWebStore


PAGES = (
    ('QuestTop', '关卡总目录', 'quest', True),
    ('MainStoryTop', '主线', 'quest', True),
    ('DailyQuestTop', '每日关卡', 'quest', True),
    ('ChallengeQuestTop', '挑战', 'quest', False),
    ('ExpeditionTop', '远征', 'quest', False),
    ('RootEntangleTop', '羁绊', 'quest', False),
    ('AnotherQuestTop', '另一篇故事', 'quest', False),
    ('SideQuestTop', '支线故事', 'quest', False),
    ('EventStoryTop', '剧情活动（条件入口）', 'event/storyEvent', False),
    ('EventMultiFrontTop', '多方面作战（条件入口）', 'event/multifront', False),
    ('EventHighStrategicCommandTop', '高难度活动（条件入口）', 'event/highStrategic', False),
)


def audit(root, base_url=None, web_overrides=None):
    root = Path(root)
    config = json.loads((root / 'config/private-server.json').read_text('utf8'))
    web = WebStore(root / config['webRoot'], config['webEntry'])
    if web_overrides is not None:
        web.local_overrides = Path(web_overrides)
    preserved = PreservedWebStore(root / config['preservedPages'])
    def resource(path):
        result = web.resolve(path)
        return preserved.resolve(path) if result[0] == 404 else result
    entry = resource('/web/index.html')[1].decode('utf8')
    guard = resource('/web/js/local/LocalUnavailableLinks.js')[1].decode('utf8')
    known_paths = set(web.routes) | set(preserved.routes)
    rows = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for name, label, directory, supported in PAGES:
        resources = []
        script = ''
        for kind, extension in [('js', 'js'), ('template', 'html'), ('css', 'css')]:
            exact = sorted(p for p in known_paths
                           if p.startswith('/web/' + kind + '/') and
                           p.endswith('/' + name + '.' + extension))
            path = exact[0] if len(exact) == 1 else '/web/%s/%s/%s.%s' % (
                kind, directory, name, extension)
            status, data, _ = resource(path)
            resources.append({'path': path, 'status': status,
                              'sha256': hashlib.sha256(data).hexdigest() if status == 200 else None})
            if kind == 'js' and status == 200:
                script = data.decode('utf8')
        row = {'page': name, 'label': label, 'implementedPage': supported,
               'resources': resources,
               'unavailableNotice': ('prefix: "#/' + name + '"') in guard}
        if base_url:
            request = urllib.request.Request(base_url.rstrip('/') + '/api/page/' + name +
                ('?value=locationList&timeStamp=1' if name == 'MainStoryTop' else ''),
                headers={'X-Web-Session-Id': 'quest-directory-audit'})
            try:
                with opener.open(request, timeout=20) as response:
                    payload = json.load(response)
                    row['apiStatus'] = response.status
                row['resultCode'] = payload.get('resultCode')
                match = re.search(r'needModelIdObj:\[(.*?)\]', script)
                required = re.findall(r'id:"([^"]+)"', match.group(1)) if match else []
                row['missingModels'] = [key for key in required if key not in payload]
                row['counts'] = {key: len(payload[key]) for key in
                    ('userQuestList', 'userChapterList', 'partList', 'locationList') if key in payload}
                if name == 'MainStoryTop':
                    row['invalidMapLocations'] = [loc.get('locationId') for loc in payload['locationList']
                        if not all(key in loc for key in ('mapDataNo', 'x', 'y', 'imageNo'))]
            except urllib.error.HTTPError as error:
                row['apiStatus'] = error.code
        rows.append(row)
    inventory = []
    for path in sorted(known_paths):
        if any(path.startswith('/web/' + kind + '/quest/')
               for kind in ('js', 'template', 'css', 'image')):
            status, data, _ = resource(path)
            inventory.append({'path': path, 'status': status,
                              'sha256': hashlib.sha256(data).hexdigest() if status == 200 else None})
    return {'scope': 'QuestTop, ordinary siblings, other-story submenu and conditional events',
            'timedHomepageRedirectPresent': bool(re.search(
                r'setInterval\([\s\S]{0,300}location\.hash\s*=\s*[\'"]#/MyPage', entry)),
            'pages': rows, 'questResourceInventory': inventory, 'nativeRenderingVerified': False,
            'note': 'Static files and API contracts do not establish gameplay or native rendering.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-root', type=Path, required=True)
    parser.add_argument('--base-url')
    parser.add_argument('--web-overrides', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.package_root, args.base_url, args.web_overrides)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'pages': len(result['pages']),
                     'timedHomepageRedirectPresent': result['timedHomepageRedirectPresent'],
                     'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
