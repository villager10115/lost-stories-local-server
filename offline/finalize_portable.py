import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'app/offline'))
from server import CHALLENGE_RECEIVE_PATHS, LOCAL_PAGE_PATHS, PRESENT_PROXY_PATHS

schema = json.loads((root / 'assets/request-schema/request-schema.json').read_text('utf8'))
server_tree = ast.parse((root / 'app/offline/server.py').read_text('utf8'))
state_tree = ast.parse((root / 'app/stateful_server/cgls/app.py').read_text('utf8'))
literal_paths = {n.value for tree in (server_tree, state_tree) for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('/api/')}
rows = []
for endpoint in schema['endpoints']:
    route = endpoint['path']
    if '/debug/' in route:
        status = '官方调试入口：不作为玩家流程'
    elif route in LOCAL_PAGE_PATHS or route in PRESENT_PROXY_PATHS and '/page/' in route:
        status = '页面模型已接入；不代表页面内全部玩法'
    elif route in CHALLENGE_RECEIVE_PATHS:
        status = '领取处理已接入；任务进度事件尚未全部复现'
    elif route in literal_paths:
        status = '源码存在处理入口；需按完整操作链验收'
    else:
        status = '未实现或尚无可核验处理入口'
    rows.append({'path': route, 'status': status, 'key': endpoint['key']})
report = {'fullOfficialGameplayReproduced': False, 'endpoints': rows,
          'counts': dict(Counter(row['status'] for row in rows))}
(root / 'reports/flow-coverage.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
lines = ['# 官服流程覆盖边界', '',
         '此包已封装离线启动与既有本地服务，不是完整官服复刻。DMM 初始化已移除。', '',
         '## 启动与资源树', '',
         'LostStories.exe → 包内 Python → 本地存档备份 → 状态服务 18866 → 页面/资源服务 18865 → 请求树预检 → Unity 客户端 → Title → MyPage。', '',
         '原始有序资源树：assets/network-structure/network-structure.json；任务资源比对：assets/quest-structure。',
         '树中的资源可返回与玩法事务完成是两项独立检查。', '',
         '## 必须补齐的核心流程', '',
         '- 战斗开始、过程与结算、奖励、任务进度更新和重登持久化尚未形成完整实现。',
         '- 觉醒、部分 KMF 成长、训练、公会、竞技场和商店业务仍有未实现接口。',
         '- 登录演出、全部原生页面交互与所有玩法没有完成逐项实机验收。',
         '- 官方调试入口不属于玩家流程；真钱支付不接入，本地模拟权益需单独实现。', '',
         '## 接口逐项清单', '', '| 接口 | 状态 |', '|---|---|']
lines.extend('| `' + r['path'] + '` | ' + r['status'] + ' |' for r in rows)
(root / 'reports/FLOW_COVERAGE.md').write_text('\n'.join(lines), encoding='utf8')

files = []
for directory in ('Client', 'app', 'assets', 'config', 'runtime', 'launcher'):
    for f in sorted((root / directory).rglob('*')):
        if not f.is_file() or '__pycache__' in f.parts or f.suffix in ('.log', '.pyc', '.portable'):
            continue
        h = hashlib.sha256()
        with f.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                h.update(block)
        files.append({'path': f.relative_to(root).as_posix(), 'bytes': f.stat().st_size, 'sha256': h.hexdigest()})
        if len(files) % 10000 == 0:
            print('Manifest hashed: ' + str(len(files)), flush=True)
exe = root / 'LostStories.exe'
files.append({'path': exe.name, 'bytes': exe.stat().st_size, 'sha256': hashlib.sha256(exe.read_bytes()).hexdigest()})
(root / 'reports/files.json').write_text(json.dumps({'files': files}, indent=2), encoding='utf8')
print(json.dumps({'files': len(files), 'bytes': sum(f['bytes'] for f in files), 'coverage': report['counts']}), flush=True)
