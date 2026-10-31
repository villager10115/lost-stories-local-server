"""Deploy the reviewed gameplay release with per-file backups and rollback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket


FILES = [
    'stateful_server/cgls/app.py', 'stateful_server/cgls/models.py',
    'stateful_server/cgls/db.py',
    'stateful_server/cgls/cosmetic_models.py',
    'stateful_server/cgls/cosmetics.py',
    'stateful_server/cgls/battles.py', 'stateful_server/cgls/battle_data.py',
    'stateful_server/cgls/battle_validation.py',
    'stateful_server/cgls/bootstrap.py',
    'stateful_server/cgls/missions.py',
    'stateful_server/cgls/gacha.py',
    'stateful_server/cgls/gacha_service.py',
    'stateful_server/cgls/gacha_selection.py',
    'stateful_server/fixtures/battle_512001.json', 'stateful_server/fixtures/battle_native_reference.json',
    'stateful_server/fixtures/battle_519001.json',
    'stateful_server/fixtures/new_account.json',
    'stateful_server/fixtures/all_quest_catalog.json',
    'stateful_server/fixtures/story_battle_plugin.json',
    'stateful_server/fixtures/shop_catalog.json',
    'stateful_server/fixtures/gacha_selectable_catalog.json',
    'stateful_server/fixtures/tutorial_quests.json',
    'stateful_server/tests/test_battles.py', 'stateful_server/tests/test_battle_data.py',
    'stateful_server/tests/test_api.py',
    'stateful_server/tests/test_costumes.py',
    'stateful_server/tests/test_missions.py',
    'stateful_server/tests/test_gacha_service.py',
    'stateful_server/tests/test_shop_account.py',
    'offline/server.py', 'offline/new_account_page.py', 'offline/test_web_artifact_guards.py',
    'offline/shop.py', 'offline/test_shop.py',
    'offline/gacha_pages.py', 'offline/test_gacha_pages.py',
    'offline/test_new_account_page.py',
    'offline/test_costume_page_contract.js',
    'offline/test_entry_navigation.js',

    'offline/test_quest_result_guard.js',
    'offline/test_account_guard.js',
    'offline/test_local_purchase_notice.js',
    'offline/test_local_gacha_perk.js',
    'offline/test_gacha_perk.js',
    'offline/preserved_pages.py', 'offline/test_server.py',
    'offline/test_preserved_pages.py',
    'offline/extract_quest_battle_catalog.py',
    'offline/test_extract_quest_battle_catalog.py',
    'offline/audit_story_battle_enemies.py',
    'offline/deploy_battle_release.py',
    'offline/verify_sqlite_snapshot_equal.py',
    'offline/verify_battle_release.py', 'offline/test_local_battle_recovery.js',
    'offline/test_skip_result_contract.js',
    'offline/web_overrides/web/index.html',
    'offline/web_overrides/web/js/local/LocalBattleRecovery.js',
    'offline/web_overrides/web/js/local/LocalQuestResultGuard.js',
    'offline/web_overrides/web/js/local/LocalGachaPerk.js',
    'offline/web_overrides/web/js/local/LocalPurchaseNotice.js',
    'offline/web_overrides/web/js/local/LocalEnhancementPage.js',
    'offline/web_overrides/web/js/kmf/KmfDevelopment.js',
    'offline/web_overrides/web/js/kmf/KmfDismantle.js',
    'offline/web_overrides/web/js/coloring/KmfColoring.js',
    'offline/web_overrides/web/js/carrying/CarryingTop.js',
    'offline/web_overrides/web/js/local/LocalAccountGuard.js',
    'offline/web_overrides/web/js/local/LocalAccountStatus.js',
    'offline/web_overrides/web/js/local/LocalUnavailableLinks.js',
]

WEB_FILES = [
    'web/js/local/LocalBattleRecovery.js',
    'web/js/local/LocalQuestResultGuard.js',
    'web/js/local/LocalGachaPerk.js',
    'web/js/local/LocalPurchaseNotice.js',
    'web/js/local/LocalEnhancementPage.js',
    'web/js/kmf/KmfDevelopment.js',
    'web/js/kmf/KmfDismantle.js',
    'web/js/coloring/KmfColoring.js',
    'web/js/carrying/CarryingTop.js',
    'web/js/local/LocalAccountGuard.js',
    'web/js/local/LocalAccountStatus.js',
    'web/js/local/LocalUnavailableLinks.js',
    'web/js/costume/CostumeTop.js',
    'web/template/costume/CostumeTop.html',
    'web/css/costume/CostumeTop.css',
    'web/image/common/detail/bg_loading_2.webp',
    'web/image/common/icon/icon_costume_favorite.webp',
    'web/image/common/icon/icon_lock.webp',
    'web/image/common/rarity/icon_rarity_on_l.webp',
    'web/image/compose/icon_information.webp',
    'web/image/costume/bg_costume.webp',
    'web/image/costume/bg_footer_1.webp',
    'web/image/costume/bg_loading_costume_1.webp',
    'web/image/costume/bg_loading_costume_2.webp',
    'web/image/costume/bg_select_costume.webp',
    'web/image/costume/character_thumbnail_line.webp',
    'web/image/costume/costume_default.webp',
    'web/image/costume/costume_pilot_thumbnail_line.webp',
    'web/image/costume/costume_thumbnail_line_1.webp',
    'web/image/costume/costume_thumbnail_line_2.webp',
    'web/image/costume/f_select_costume.webp',
    'web/image/costume/icon_arrow_s.webp',
    'web/image/costume/overwrap_nonpossessed_costume_JP.webp',
    'web/image/costume/overwrap_seted_costume_JP.webp',
    'web/image/costume/pnl_costume_1.webp',
    'web/image/costume/pnl_costume_2.webp',
    'web/image/costume/text_selected_costume_JP.webp',
    'web/image/deck/icon_arrow_l.webp',
    'web/image/expedition/bg_footer_1.webp',
    'web/image/item/main/small/icon_item_arena_medal.webp',
    'web/image/user/ChangeBackground/overwrap_nonpossessed_JP.webp',
    'web/image/user/ChangeBackground/pnl_thumbnail_line_4.webp',
]

COSTUME_FILES = [
    'stateful_server/cgls/app.py',
    'stateful_server/cgls/db.py',
    'stateful_server/cgls/models.py',
    'stateful_server/cgls/cosmetic_models.py',
    'stateful_server/cgls/cosmetics.py',
    'stateful_server/tests/test_costumes.py',
    'offline/new_account_page.py',
    'offline/test_new_account_page.py',
    'offline/test_costume_page_contract.js',
    'offline/test_costume_render.cjs',
    'offline/deploy_battle_release.py',
    'research/costume-source-20261031.json',
]

COSTUME_WEB_FILES = [
    'web/js/costume/CostumeTop.js',
    'web/template/costume/CostumeTop.html',
    'web/css/costume/CostumeTop.css',
    *[path for path in WEB_FILES if path.startswith('web/image/')],
]
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source, package, backup, deploy=False, report_name='GAMEPLAY_REPAIR_20261025.md',
        receipt_name='gameplay-deployment.json', report_source=None,
        files=None, web_files=None):
    report_source = Path(report_source) if report_source else source/report_name
    if Path(report_name).name != report_name or Path(receipt_name).name != receipt_name:
        raise ValueError('Report and receipt must be plain file names')
    pairs={('app/'+rel):(source/rel) for rel in FILES}
    selected_files = FILES if files is None else files
    selected_web_files = WEB_FILES if web_files is None else web_files
    pairs={('app/'+rel):(source/rel) for rel in selected_files}
    for rel in ('web/index.html', *selected_web_files):
        pairs['assets/static-preview/local_overrides/'+rel]=source/'offline/web_overrides'/rel
    pairs['PROGRESS.md']=source/'PROGRESS.md'
    pairs['reports/'+report_name]=report_source
    manifest_path=package/'reports/files.json'
    original_manifest=manifest_path.read_bytes()
    manifest=json.loads(original_manifest)
    index={r['path']:r for r in manifest['files']}
    changes=[]
    manifest_updates=[]
    for rel,src in pairs.items():
        target=(package/rel).resolve()
        if package.resolve() not in target.parents:raise RuntimeError('Target escaped package')
        if not src.is_file():raise RuntimeError('Missing release source: '+rel)
        old=index.get(rel)
        desired=digest(src)
        actual=digest(target) if target.exists() else None
        if target.exists() and old and actual!=old['sha256'] and actual!=desired:
            raise RuntimeError('Package file changed since its manifest: '+rel)
        if actual==desired:
            if not old or old['sha256']!=desired or old['bytes']!=src.stat().st_size:
                manifest_updates.append({'path':rel,'bytes':src.stat().st_size,'sha256':desired,
                                        'oldSha256':old['sha256'] if old else None})
            continue
        changes.append({'path':rel,'bytes':src.stat().st_size,'sha256':desired,
                        'oldSha256':actual})
    plan={'package':str(package),'backup':str(backup),'files':changes,
          'manifestUpdates':manifest_updates,'formalDatabaseWrites':False,
          'nativeClientWrites':False}
    plan_path=source/'snapshots'/(Path(receipt_name).stem+'-plan.json')
    plan_path.write_text(json.dumps(plan,indent=2),encoding='utf8')
    if not deploy:
        print(json.dumps({'plannedWrites':len(changes),'plan':str(plan_path)}));return
    config=json.loads((package/'config/private-server.json').read_text('utf8'))
    for key in ('pagePort','statePort','debugPort'):
        with socket.socket() as sock:
            sock.settimeout(.5)
            if sock.connect_ex(('127.0.0.1',config[key]))==0:
                raise RuntimeError('Close the local game and services before deploying')
    backup.mkdir(parents=True,exist_ok=False)
    (backup/'files.json.before').write_bytes(original_manifest)
    for row in changes:
        target=package/row['path'];saved=backup/row['path']
        if target.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
    written=[]
    try:
        for row in changes:
            rel=row['path'];target=package/rel;target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.gameplay-tmp')
            shutil.copy2(pairs[rel],temporary);os.replace(temporary,target);written.append(row)
            if digest(target)!=row['sha256']:raise RuntimeError('Post-write hash mismatch')
            index[rel]={k:row[k] for k in ('path','bytes','sha256')}
        for row in manifest_updates:
            index[row['path']]={k:row[k] for k in ('path','bytes','sha256')}
        manifest['files']=sorted(index.values(),key=lambda row:row['path'])
        temporary=manifest_path.with_suffix('.gameplay-tmp')
        temporary.write_text(json.dumps(manifest,indent=2),encoding='utf8');os.replace(temporary,manifest_path)
    except BaseException:
        for row in reversed(written):
            target=package/row['path'];saved=backup/row['path']
            if row['oldSha256'] is None:target.unlink()
            else:shutil.copy2(saved,target)
        manifest_path.write_bytes(original_manifest)
        raise
    plan['manifestEntries']=len(index)
    (backup/'deployment.json').write_text(json.dumps(plan,indent=2),encoding='utf8')
    (package/'reports'/receipt_name).write_text(json.dumps(plan,indent=2),encoding='utf8')
    print(json.dumps({'writes':len(changes),'manifestEntries':len(index),'backup':str(backup)}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=Path('D:/codegeass'))
    p.add_argument('--package',type=Path,default=Path('D:/LostStories_Offline'))
    p.add_argument('--backup',type=Path,required=True);p.add_argument('--deploy',action='store_true')
    p.add_argument('--report',default='GAMEPLAY_REPAIR_20261025.md')
    p.add_argument('--report-source',type=Path)
    p.add_argument('--receipt',default='gameplay-deployment.json')
    p.add_argument('--profile',choices=('full','costume'),default='full')
    a=p.parse_args()
    files=COSTUME_FILES if a.profile=='costume' else None
    web_files=COSTUME_WEB_FILES if a.profile=='costume' else None
    run(a.source,a.package,a.backup,a.deploy,a.report,a.receipt,a.report_source,
        files=files,web_files=web_files)
