"""Whole-release HTTP, restart and catalog checks on disposable save copies."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace
import urllib.request

import uvicorn


def run(source, package, output):
    output.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(source/'offline'),str(source/'stateful_server')]
    from cgls.app import create_app
    from cgls.battle_data import BattleData, BattleError
    from server import LocalServer
    config=json.loads((package/'config/private-server.json').read_text('utf8'))
    checks={}
    for key in ('stateDatabase','pageDatabase','deckDatabase'):
        srcpath=package/config[key]
        with closing(sqlite3.connect(srcpath.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(output/(key+'.sqlite'))) as dst:
            src.backup(dst)
            checks[key]={'integrity':dst.execute('pragma integrity_check').fetchone()[0],
                         'foreignKeys':dst.execute('pragma foreign_key_check').fetchall(),
                         'logicalMatch':list(src.iterdump())==list(dst.iterdump())}
        assert checks[key]=={'integrity':'ok','foreignKeys':[],'logicalMatch':True}
    report={'backups':checks,'passes':[],'formalSaveWrites':False,'nativeGameLaunched':False}
    previous=None
    skipped = None
    for iteration in range(3):
        app=create_app(output/'stateDatabase.sqlite',source/'stateful_server/fixtures/gacha_1005.json',
                       masterdata_dir=package/config['masterdata'])
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));state_port=s.getsockname()[1]
        state=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=state_port,log_level='error'))
        st=threading.Thread(target=state.run,daemon=True);st.start()
        deadline=time.monotonic()+20
        while not state.started and time.monotonic()<deadline:time.sleep(.05)
        assert state.started
        base=f'http://127.0.0.1:{state_port}'
        page=LocalServer(0,output/'pageDatabase.sqlite',deck_database=output/'deckDatabase.sqlite',
            masterdata=package/config['masterdata'],gacha_upstream=base,
            gacha_state_url=base+'/api/local/page-state',gacha_static=package/config.get('gachaStatic','assets/gacha-static'),
            preserved_pages_cache=package/config['preservedPages'],web_root=package/config['webRoot'],web_entry=config['webEntry'])
        pt=threading.Thread(target=page.serve_forever,daemon=True);pt.start()
        def request(path,payload=None,state_api=False,request_id=None):
            headers={'Content-Type':'application/json','X-Web-Session-Id':'release-copy-test'}
            if request_id:headers['X-Request-Id']=request_id
            req=urllib.request.Request((base if state_api else 'http://'+page.authority)+path,
                data=None if payload is None else json.dumps(payload).encode(),headers=headers)
            with urllib.request.urlopen(req,timeout=45) as reply:
                return json.loads(reply.read())
        try:
            home=request('/api/page/MyPage')
            for name in ('QuestBackground','QuestResult'):
                model=request('/api/page/'+name)
                # Required names are taken from the original preserved module.
                script=(source/'snapshots/battle-system-audit'/f'{name}.js')
                if not script.exists():script=Path('D:/codegeass/snapshots/battle-system-audit')/f'{name}.js'
                names=re.findall(r'\{id:"([^"]+)"',script.read_text('utf8').split('needModelIdObj:')[1].split('fetch:')[0])
                assert all(name in model for name in names), (name,[n for n in names if n not in model])
                report['passes'].append(name+' models')
            if iteration==0:
                # Any previous interrupted battle exists only in this copy.
                local=request('/api/local/page-state',state_api=True)
                main_story=request('/api/page/MainStoryTop')
                story_by_id={row['questId']:row for row in main_story['userQuestList']}
                assert story_by_id[101003]['questStatus']=='OPENED'
                assert story_by_id[101121]['questStatus']=='OPENED'
                assert story_by_id[101121]['isNew'] is True
                assert story_by_id[101122]['questStatus']=='CANDIDATE'
                missions=request('/api/page/MissionTop')
                for name in ('userDailyChallengeList','userWeeklyChallengeList',
                             'userTotalChallengeList','userBeginnerChallengeList',
                             'userLimitedChallengeList','userSideTotalChallengeList',
                             'userEntangleTotalChallengeList'):
                    assert isinstance(missions.get(name),list),name
                assert any(row['clearedCount'] for row in
                           missions['userTotalChallengeList'])
                shop=request('/api/page/ShopTop')
                assert len(shop['shopList'])==11, [row['shopId'] for row in shop['shopList']]
                assert sum(len(row['shopItemList']) for row in shop['shopList'])==343
                local_shop=next(row for row in shop['shopList'] if row['shopId']==99001)
                assert len(local_shop['shopItemList'])==3
                shop_buy=request('/api/shop/buy',{
                    'shopId':99001,'shopItemId':990001,'num':1})
                assert shop_buy['resultCode']=='success',shop_buy
                assert {row['itemId']:row['quantity'] for row in shop_buy['userItemList']}['MONEY']>=3000
                report['passes']+=['ShopTop retains 10 stores and appends 3 local money products',
                    'free paid-stone purchase separates MONEY and PRESENTED_MONEY']
                mission_claim=request('/api/challenge/receive/all',{})
                assert mission_claim['resultCode']=='success',mission_claim
                story_end=request('/api/quest/story/end',{'questId':101003})
                assert story_end['userQuestList'][0]['questStatus']=='CLEARED'
                report['passes']+=['main-story prerequisite closure',
                    'MissionTop retained task progress','story end updates story models',
                    'challenge receive all forwards locally']
                if local.get('localActiveBattle'):
                    request('/api/local/battle/retire',{'userQuestResultId':local['localActiveBattle']['userQuestResultId']})
                units=request('/api/local/units',state_api=True)
                pilot=next((p for p in units['userCardList'] if p['cardId']==103004),units['userCardList'][0])
                kmf=next(k for k in units['userKnightmareFrameList'] if not k.get('isInStorage'))
                payload={'questId':512001,'deckType':'MAIN1','userCardIdList':[pilot['userCardId']],
                         'userKnightmareFrameIdList':[kmf['userKnightmareFrameId']]}
                battle_payload = payload.copy()
                before=request('/api/local/state',state_api=True)
                denied=request('/api/battle/start',{**payload,'questId':304104})
                assert denied['resultCode']=='error'
                assert request('/api/local/state',state_api=True)['stamina']==before['stamina']
                previous=request('/api/battle/start',payload,request_id='release-start')
                assert previous['resultCode']=='success',previous
                assert previous['battle']==request('/api/battle/start',payload,request_id='release-retry')['battle']
                report['passes']+=['unsupported quest causes no charge','start and active retry']
            elif iteration==1:
                local=request('/api/local/page-state',state_api=True)
                assert local['localActiveBattle']['userQuestResultId']==previous['userQuestResultId']
                p=previous['battle']['playerData']['pilotStatusData'][0]
                result={'result':'WIN','clearRank':'S','defeatCount':16,'usedPlayerSkill':False,'isRetryWeakened':False,
                    'isAchieveMission1':True,'isAchieveMission2':True,'isAchieveMission3':True,
                    'dropIdList':[e['dropId'] for w in previous['battle']['questData']['waveData'] for e in w['waveEventData'] if 'dropId' in e],
                    'battleResultDetailData':{'pilotResultData':[{'userPilotId':p['userPilotId'],'userKnightmareId':p['userKnightmareId'],
                        'totalDamage':1000,'receivedDamage':0,'pilotSkillUseCount1':1,'pilotSkillUseCount2':0,'knightmareSkillUseCount':0}]}}
                payload={'userQuestResultId':previous['userQuestResultId'],'battleResult':result}
                ended=request('/api/battle/end',payload)
                assert ended['resultCode']=='success',ended
                after=request('/api/local/state',state_api=True)
                retry=request('/api/battle/end',payload)
                assert retry['battleResult']==ended['battleResult']
                assert request('/api/local/state',state_api=True)==after
                result_page=request('/api/page/QuestResult')
                progress=next(r for r in result_page['userQuestList'] if r['questId']==512001)
                assert progress['bestQuestRank']=='S'
                assert result_page['gameUser']['experience']>=8
                assert request('/api/battle/skip',{'questId':512001})['resultCode']=='error'
                report['passes']+=['active battle after restart','end and duplicate end','result and home persistence','malformed skip is explicit']
                # This developer grant is confined to the three disposable DBs.
                request('/api/local/dev-state',{'items':{'SKIP_QUEST':2}},state_api=True)
                before_skip=request('/api/local/state',state_api=True)
                before_skip_page=request('/api/page/MyPage')
                skipped=request('/api/battle/skip',battle_payload,request_id='release-skip')
                assert skipped['resultCode']=='success',skipped
                assert skipped['battleResult']['result']=='SKIP'
                assert skipped['gameUser']['experience']>=16
                # Backbone joins the static card by cardId; HTTP user cards
                # carry derived stats, not a nested copy of the static master.
                assert all(all(key in c for key in ('cardId','hp','strength','revisionClass'))
                           for c in skipped['userCardList'])
                assert skipped['userDailyQuestList'][0]['dailyClearCount']==ended['userDailyQuestList'][0]['dailyClearCount']+1
                after_skip=request('/api/local/state',state_api=True)
                assert after_skip['stamina']==before_skip['stamina']-10
                assert after_skip['skipTickets']==before_skip['skipTickets']-1
                assert after_skip['freeSakuradite']==before_skip['freeSakuradite']
                (output/'skip-result-model.json').write_text(json.dumps({
                    'before':before_skip_page,'after':request('/api/page/MyPage'),
                    'response':skipped,'formation':battle_payload},ensure_ascii=False),encoding='utf8')
                report['passes']+=['skip charges once and preserves first-clear rewards','skip result page models and daily count']
            else:
                retry=request('/api/battle/skip',battle_payload,request_id='release-skip')
                assert retry['battleResult']==skipped['battleResult']
                assert retry['userQuestResultId']==skipped['userQuestResultId']
                assert request('/api/local/state',state_api=True)==after_skip
                assert request('/api/local/page-state',state_api=True)['localActiveBattle'] is None
                report['passes'].append('skip retry after restart preserves resources')
        finally:
            page.shutdown();page.server_close();pt.join()
            state.should_exit=True;st.join(timeout=20);app.state.engine.dispose()
    data=BattleData(package/config['masterdata'])
    pilot=SimpleNamespace(user_card_id='fixture-pilot',mst_pilot_id=103004,level=1,
        awakening_level=0,limit_break=0,skill_levels=[],unlocked_feature_ids=[])
    weapon=next(iter(data.weapons.values()))
    kmf=SimpleNamespace(user_kmf_id='fixture-kmf',mst_kmf_id=weapon['knightmareFrameId'],
        customization_id=weapon['knightmareFrameCustomizeId'],revision=0,revision_class=1)
    coverage={'pilots':0,'kmfs':0,'unsupported':[], 'unexpectedErrors':[]}
    for cid in data.cards:
        pilot.mst_pilot_id=cid
        try:data.assemble([(pilot,kmf)],{});coverage['pilots']+=1
        except BattleError as exc:coverage['unsupported'].append({'cardId':cid,'reason':str(exc)})
        except (KeyError,ValueError,TypeError) as exc:coverage['unexpectedErrors'].append({'cardId':cid,'error':repr(exc)})
    pilot.mst_pilot_id=103004
    for wid,w in data.weapons.items():
        kmf.customization_id=wid;kmf.mst_kmf_id=w['knightmareFrameId']
        try:data.assemble([(pilot,kmf)],{});coverage['kmfs']+=1
        except BattleError as exc:coverage['unsupported'].append({'weaponId':wid,'reason':str(exc)})
        except (KeyError,ValueError,TypeError) as exc:coverage['unexpectedErrors'].append({'weaponId':wid,'error':repr(exc)})
    report['nativeDtoCoverage']=coverage
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passes':report['passes'],'coverage':{k:v for k,v in coverage.items() if k!='unsupported'},
                     'unsupported':len(coverage['unsupported']),'report':str(output/'report.json')}))
    assert not coverage['unexpectedErrors'], 'Unexpected native adapter errors; see report'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--package',type=Path,default=Path('D:/LostStories_Offline'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();run(args.source,args.package,args.output)
