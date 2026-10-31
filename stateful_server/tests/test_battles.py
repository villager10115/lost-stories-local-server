from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from cgls.app import create_app
from cgls.battles import BattleService, BattleError
from cgls.models import LocalBattle, LocalBattleProgress, UserPilot, UserWallet, UserGameItem
from cgls.models import UserKmf
from cgls.bootstrap import ensure_local_user

ROOT = Path(__file__).resolve().parents[1]
MASTER = Path('D:/LostStories_Offline/assets/masterdata')


class BattleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name)/'state.sqlite'
        self.app = create_app(self.db,ROOT/'fixtures/gacha_1005.json',masterdata_dir=MASTER)
        self.client = TestClient(self.app)
        units = self.client.get('/api/local/units').json()
        self.payload={'questId':512001,'deckType':'MAIN1',
            'userCardIdList':[r['userCardId'] for r in units['userCardList']],
            'userKnightmareFrameIdList':[r['userKnightmareFrameId'] for r in units['userKnightmareFrameList']]}
        with self.app.state.session_factory() as session:
            self.uid = ensure_local_user(session).id
        self.time = datetime.fromisoformat('2026-10-21T12:00:00+09:00')
        self.service=BattleService(self.app.state.session_factory,self.uid,MASTER,lambda:self.time)

    def tearDown(self):
        self.app.state.engine.dispose()
        self.tmp.cleanup()

    def win(self,start):
        return {'result':'WIN','clearRank':'S',
                'defeatCount':start['battle']['questData']['enemyNum'],
                'usedPlayerSkill':False, 'isRetryWeakened':False,
                'battleResultDetailData':{'pilotResultData':[
                    {'userPilotId':p['userPilotId'],'userKnightmareId':p['userKnightmareId'],
                     'totalDamage':100, 'receivedDamage':0, 'pilotSkillUseCount1':1,
                     'pilotSkillUseCount2':0, 'knightmareSkillUseCount':0}
                    for p in start['battle']['playerData']['pilotStatusData']]},
                'isAchieveMission1':True,'isAchieveMission2':True,'isAchieveMission3':True,
                'dropIdList':[e['dropId'] for w in start['battle']['questData']['waveData']
                              for e in w['waveEventData'] if 'dropId' in e]}

    def test_start_finish_retry_and_restart(self):
        start=self.service.start(self.payload,'start-1')
        self.assertEqual(start,self.service.start(self.payload,'start-1'))
        self.assertEqual(start,self.service.start(self.payload,'start-2'))
        self.assertEqual(start['battle']['questData']['mapDataNo'],1084001)
        self.assertEqual(len(start['battle']['questData']['waveData'][0]['waveEventData']),16)
        self.assertEqual(start['battle']['playerData']['pilotStatusData'][0]['pilotId'],103004)
        response=self.service.finish(start['userQuestResultId'],self.win(start))
        self.assertEqual(response['userDailyQuestList'][0]['dailyClearCount'],1)
        self.assertEqual(response,self.service.finish(start['userQuestResultId'],self.win(start)))
        reopened=BattleService(self.app.state.session_factory,self.uid,MASTER,lambda:self.time)
        self.assertEqual(response,reopened.finish(start['userQuestResultId'],self.win(start)))
        with self.app.state.session_factory() as session:
            self.assertEqual(session.get(UserWallet,self.uid).stamina,125)
            self.assertEqual(session.get(UserWallet,self.uid).free_sakuradite,400)
            self.assertEqual(session.get(UserGameItem,(self.uid,'CARD_CRYSTAL_STAR_BRONZE')).quantity,32)
            self.assertEqual(len([row for row in response['battleResult']['rewardList']
                if row['code']=='CARD_CRYSTAL_STAR_BRONZE']),32)
        state=self.client.get('/api/local/page-state').json()
        self.assertEqual(state['userQuestList'][0]['bestQuestRank'],'S')
        self.assertEqual(state['battleExperience'],8)

    def test_daily_drop_boost_consumes_one_item_and_doubles_drops(self):
        with self.app.state.session_factory() as session:
            session.add(UserGameItem(
                user_id=self.uid,item_id='DAILY_QUEST_DROP_BOOST',quantity=1))
            session.commit()
        payload = {**self.payload, 'usedDailyQuestDropBoostItem': True}
        start = self.service.start(payload, 'boosted-daily')
        with self.app.state.session_factory() as session:
            self.assertEqual(session.get(UserGameItem,(
                self.uid,'DAILY_QUEST_DROP_BOOST')).quantity,0)
        response = self.service.finish(
            start['userQuestResultId'],self.win(start))
        rows = [row for row in response['battleResult']['rewardList']
                if row['code']=='CARD_CRYSTAL_STAR_BRONZE']
        self.assertEqual(len(rows),32)
        self.assertTrue(all(row['num']==2 for row in rows))
        with self.app.state.session_factory() as session:
            self.assertEqual(session.get(UserGameItem,(
                self.uid,'CARD_CRYSTAL_STAR_BRONZE')).quantity,64)

    def test_captured_519001_full_local_lifecycle(self):
        payload={**self.payload,'questId':519001}
        start=self.service.start(payload,'519001-start')
        quest=start['battle']['questData']
        self.assertEqual(quest['mapDataNo'],1022001)
        self.assertEqual(quest['fieldData']['fieldId'],1022)
        self.assertEqual(quest['enemyNum'],20)
        self.assertEqual(len(quest['waveData'][0]['waveEventData']),20)
        self.assertEqual(sum('dropId' in event for event in quest['waveData'][0]['waveEventData']),20)
        response=self.service.finish(start['userQuestResultId'],self.win(start))
        self.assertEqual(response['userQuestList'][0]['questId'],519001)
        self.assertEqual(response['userQuestList'][0]['bestQuestRank'],'S')
        self.assertEqual(response['userDailyQuestList'][0]['dailyTypeName'],'KMF_FAR')
        self.assertEqual(response['userDailyQuestList'][0]['dailyClearCount'],1)
        far_rewards = [row for row in response['battleResult']['rewardList']
                      if row['code']=='KMF_CHIP_FAR_BRONZE']
        self.assertEqual(len(far_rewards),40)
        self.assertTrue(all(row['num']==1 for row in far_rewards))
        page=self.client.get('/api/local/page-state').json()
        self.assertEqual({row['dailyTypeName'] for row in page['userDailyQuestList']},
                         {'GOLD_CARD_EXP','CARD_REVISION_BISHOP_STAR',
                          'CARD_REVISION_KNIGHT_QUEEN','CARD_REVISION_ROOK_KING',
                          'KMF_NEAR','KMF_FAR'})
        self.assertIn(519001,{row['questId'] for row in page['userQuestList']})

    def test_catalog_story_battle_lifecycle_uses_stage_enemy_pool(self):
        payload={**self.payload,'questId':101101}
        started=self.client.post('/api/battle/start',json=payload,
            headers={'X-Request-Id':'story-101101'})
        self.assertEqual(started.status_code,200,started.text)
        start=started.json()
        quest=start['battle']['questData']
        self.assertEqual(quest['questId'],101101)
        self.assertEqual(quest['mapDataNo'],1001001)
        self.assertEqual(quest['enemyNum'],10)
        self.assertEqual({row['npcId'] for row in quest['npcStatusData']},{100001})
        self.assertEqual(len(quest['waveData'][0]['waveEventData']),10)
        self.assertFalse(any('dropId' in row for row in quest['waveData'][0]['waveEventData']))
        finished=self.client.post('/api/battle/end',json={
            'userQuestResultId':start['userQuestResultId'],
            'battleResult':self.win(start),
        })
        self.assertEqual(finished.status_code,200,finished.text)
        reply=finished.json()
        self.assertEqual(reply['resultCode'],'success')
        self.assertEqual(reply['userQuestList'][0]['questId'],101101)
        self.assertEqual(reply['userQuestList'][0]['bestQuestRank'],'S')
        self.assertEqual(reply['userDailyQuestList'],[])
        skip_rows = [row for row in reply['battleResult']['rewardList']
                     if row['code']=='SKIP_QUEST']
        self.assertEqual(len(skip_rows),1)
        self.assertEqual(skip_rows[0]['num'],1)
        page=self.client.get('/api/local/page-state').json()
        self.assertEqual(page['gameItems'].get('SKIP_QUEST'),1)
        self.assertIn(101101,{row['questId'] for row in page['userQuestList']})

    def test_all_boss_invasion_condition_settles(self):
        payload={**self.payload,'questId':101125}
        start=self.service.start(payload,'condition-three')
        self.assertEqual(
            start['battle']['questData']['winLoseConditionData']['condition'],
            'INVADED_DESTROY_ALL_BOSS_2')
        result=self.win(start)
        result['battleResultDetailData']['pilotResultData'][0][
            'pilotSkillUseCount1']=2
        reply=self.service.finish(start['userQuestResultId'],result)
        self.assertEqual(reply['battleResult']['result'],'WIN')
        self.assertEqual(reply['userQuestList'][0]['bestQuestRank'],'S')

    def test_current_5_7_1_story_battle_lifecycle(self):
        payload={**self.payload,'questId':418101}
        start=self.service.start(payload,'story-418101')
        quest=start['battle']['questData']
        self.assertEqual(quest['mapDataNo'],1129001)
        self.assertEqual(quest['enemyNum'],30)
        self.assertEqual({row['npcId'] for row in quest['npcStatusData']},{210003})
        events=quest['waveData'][0]['waveEventData']
        self.assertEqual(len(events),30)
        self.assertEqual({row['npcId'] for row in events},{210003})
        self.assertEqual(events[0]['timeMilliSeconds'],3000)
        self.assertEqual(events[-1]['timeMilliSeconds'],177000)
        self.assertFalse(any('dropId' in row for row in events))
        result=self.win(start)
        result['battleResultDetailData']['pilotResultData'][0]['pilotSkillUseCount1']=3
        reply=self.service.finish(start['userQuestResultId'],result)
        self.assertEqual(reply['resultCode'],'success')
        self.assertEqual(reply['userQuestList'][0]['questId'],418101)
        self.assertEqual(reply['userDailyQuestList'],[])

    def test_story_battle_plugin_status_api(self):
        reply=self.client.get('/api/local/battle-catalog')
        self.assertEqual(reply.status_code,200,reply.text)
        data=reply.json()
        self.assertEqual(data['storyBattleCount'],858)
        self.assertEqual(data['tutorialBattleCount'],1)
        self.assertEqual(data['additionalBattleCount'],3079)
        self.assertEqual(data['battleCount'],3938)
        self.assertEqual(data['supportedCount'],3845)
        self.assertEqual(data['rejectedCount'],93)
        self.assertIn(1000,data['supportedQuestIds'])

    def test_catalogued_activity_battles_start_and_settle(self):
        for quest_id in (810101, 941104, 950041, 602110):
            with self.subTest(questId=quest_id):
                payload={**self.payload,'questId':quest_id}
                start=self.service.start(payload,'activity-'+str(quest_id))
                self.assertEqual(start['battle']['questData']['questId'],quest_id)
                reply=self.service.finish(
                    start['userQuestResultId'],self.win(start))
                self.assertEqual(reply['userQuestList'][0]['questStatus'],'CLEARED')

    def test_entangle_card_and_kmf_deck_constraints_are_enforced(self):
        with self.app.state.session_factory() as session:
            session.add(UserPilot(
                user_id=self.uid,user_card_id='event-pilot',
                mst_pilot_id=102001,mst_chara_id=102,skill_levels=[1,1]))
            session.add(UserKmf(
                user_id=self.uid,user_kmf_id='event-kmf',mst_kmf_id=1001,
                customization_id=100101,revision_class=1))
            session.commit()
        payload={**self.payload,'questId':961201,
                 'userCardIdList':['event-pilot'],
                 'userKnightmareFrameIdList':['event-kmf']}
        start=self.service.start(payload,'entangle-valid')
        self.service.finish(start['userQuestResultId'],{'result':'RETIRE'})
        units=self.client.get('/api/local/units').json()
        foreign_card=next(row['userCardId'] for row in units['userCardList']
                           if row['cardId']==113001)
        with self.assertRaisesRegex(BattleError,'指定されたカード'):
            self.service.start({**payload,
                'userCardIdList':[foreign_card]},'entangle-invalid-card')

    def test_story_battle_catalog_detail_api(self):
        reply=self.client.get('/api/local/battle-catalog/418101')
        self.assertEqual(reply.status_code,200,reply.text)
        data=reply.json()
        self.assertEqual(data['quest']['name'],'7 - 1')
        self.assertEqual(data['requiredQuest']['questId'],417110)
        self.assertFalse(data['previousOnlyStoryQuest']['found'])
        self.assertEqual(data['previousOnlyStoryQuest']['questId'],417013)
        self.assertEqual(self.client.get('/api/local/battle-catalog/999999').status_code,404)

    def test_tutorial_battle_persists_next_tutorial_stage(self):
        payload={**self.payload,'questId':1000}
        start=self.service.start(payload,'tutorial-1000')
        self.assertEqual(start['battle']['questData']['questType'],'TUTORIAL')
        self.assertEqual(start['battle']['questData']['mapDataNo'],1010005)
        self.assertEqual(start['battle']['questData']['enemyNum'],16)
        request={'userQuestResultId':start['userQuestResultId'],
                 'battleResult':self.win(start)}
        self.assertEqual(self.client.post('/api/battle/end',json=request).status_code,200)
        state=self.client.get('/api/local/battle-state').json()
        self.assertEqual(state['tutorialId'],'TU0500')
        self.assertEqual(state['battleExperience'],5)

    def test_battle_catalog_detail_api_reports_chain_context(self):
        reply=self.client.get('/api/local/battle-catalog/101101')
        self.assertEqual(reply.status_code,200,reply.text)
        data=reply.json()
        self.assertEqual(data['questId'],101101)
        self.assertTrue(data['status']['supported'])
        self.assertGreater(data['chapter']['battleCount'],0)
        self.assertIsNotNone(data['globalNextBattle'])
        missing=self.client.get('/api/local/battle-catalog/999999999')
        self.assertEqual(missing.status_code,404)

    def test_finish_card_updates_follow_sortie_order(self):
        units=self.client.get('/api/local/units').json()
        cards=[row['userCardId'] for row in units['userCardList'][:2]][::-1]
        kmfs=[row['userKnightmareFrameId']
              for row in units['userKnightmareFrameList'][:2]][::-1]
        payload={**self.payload,'questId':101101,
                 'userCardIdList':cards,'userKnightmareFrameIdList':kmfs}
        start=self.service.start(payload,'formation-order')
        expected=[row['userPilotId'] for row in
                  start['battle']['playerData']['pilotStatusData']]
        self.assertEqual(expected,cards)
        reply=self.service.finish(start['userQuestResultId'],self.win(start))
        self.assertEqual(
            [row['userCardId'] for row in reply['userCardList']], expected)
        self.assertEqual(reply['gameUser']['experience'],10)
        self.assertGreater(reply['gameUser']['totalExpForNextLevel'],
                       reply['gameUser']['experience'])
        for row in reply['userCardList']:
            self.assertEqual(row['revisionClass'],1)
            self.assertIn('cost',row)
            self.assertIn('nearAttackAdjust',row)

    def test_saved_kmf_color_is_in_native_battle_dto(self):
        units=self.client.get('/api/local/units').json()
        user_kmf_id=units['userKnightmareFrameList'][0][
            'userKnightmareFrameId']
        colored=self.client.post('/api/knightmareFrame/color',json={
            'userKnightmareFrameId':user_kmf_id,
            'customColorR':21,
            'customColorG':22,
            'customColorB':23})
        self.assertEqual(colored.status_code,200,colored.text)

        start=self.service.start(self.payload,'saved-kmf-color')
        native=next(row for row in start['battle']['playerData']
            ['knightmareStatusData']
            if row['userKnightmareId']==user_kmf_id)
        self.assertFalse(native['isDefaultColor'])
        self.assertEqual(
            (native['customColorR'],native['customColorG'],
             native['customColorB']),(21,22,23))

    def test_rank_up_settlement_returns_all_status_models(self):
        with self.app.state.session_factory() as session:
            row=session.get(LocalBattleProgress,(self.uid,0))
            state=dict(row.state)
            state['experience']=10
            row.state=state
            session.commit()
        start=self.service.start({
            **self.payload,'questId':101101},'rank-up-statuses')
        start_status_ids={row['statusId'] for row in start['userStatusList']}
        self.assertIn('MAX_DECK',start_status_ids)
        reply=self.service.finish(start['userQuestResultId'],self.win(start))
        self.assertEqual(reply['gameUser']['rank'],2)
        status_ids={row['statusId'] for row in reply['userStatusList']}
        self.assertTrue({
            'ACP','MAX_ACP','MAX_DECK','MAX_FRIEND','UEP','MAX_UEP',
            'BTP','MAX_BTP'} <= status_ids)

    def test_distinct_cards_for_same_character_can_deploy_together(self):
        units=self.client.get('/api/local/units').json()
        with self.app.state.session_factory() as session:
            session.add_all([
                UserPilot(user_id=self.uid,user_card_id='same-chara-card-1',
                          mst_pilot_id=101001,mst_chara_id=101,skill_levels=[1,1]),
                UserPilot(user_id=self.uid,user_card_id='same-chara-card-2',
                          mst_pilot_id=101002,mst_chara_id=101,skill_levels=[1,1]),
            ])
            session.commit()
        payload={
            **self.payload,
            'questId':101101,
            'userCardIdList':['same-chara-card-1','same-chara-card-2'],
            'userKnightmareFrameIdList':[
                row['userKnightmareFrameId']
                for row in units['userKnightmareFrameList'][:2]],
        }
        start=self.service.start(payload,'same-character-different-cards')
        chara_ids=[row['charaId'] for row in start['battle']['playerData']['pilotStatusData']]
        self.assertEqual(len(chara_ids),2)
        self.assertEqual(len(set(chara_ids)),1)

    def test_story_player_skill_unused_mission_is_verified(self):
        payload={**self.payload,'questId':108201}
        start=self.service.start(payload,'story-108201')
        invalid=self.win(start)
        invalid['usedPlayerSkill']=True
        with self.assertRaisesRegex(BattleError,'Player-skill mission'):
            self.service.finish(start['userQuestResultId'],invalid)
        valid=self.win(start)
        valid['usedPlayerSkill']=True
        valid['isAchieveMission3']=False
        reply=self.service.finish(start['userQuestResultId'],valid)
        self.assertEqual(reply['resultCode'],'success')
        self.assertFalse(reply['userQuestList'][0]['clearedMission3'])

    def test_api_and_malformed_ownership(self):
        bad={**self.payload,'userCardIdList':['not-owned']}
        response=self.client.post('/api/battle/start',json=bad,headers={'X-Request-Id':'invalid'})
        self.assertEqual(response.status_code,400)
        response=self.client.post('/api/battle/start',json=self.payload,headers={'X-Request-Id':'http-start'})
        self.assertEqual(response.status_code,200,response.text)
        start=response.json()
        result=self.client.post('/api/battle/end',json={'userQuestResultId':start['userQuestResultId'],'battleResult':self.win(start)})
        self.assertEqual(result.status_code,200,result.text)

    def test_invalid_drop_rollback_failure_refund_and_concurrency(self):
        start=self.service.start(self.payload,'start')
        invalid=self.win(start)
        invalid['dropIdList'].append('forged-drop')
        with self.assertRaises(BattleError):
            self.service.finish(start['userQuestResultId'],invalid)
        with patch.object(Session,'commit',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):
                self.service.finish(start['userQuestResultId'],self.win(start))
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(lambda _:self.service.finish(start['userQuestResultId'],{'result':'RETIRE'}),range(6)))
        self.assertTrue(all(r==replies[0] for r in replies))
        with self.app.state.session_factory() as session:
            self.assertEqual(session.get(UserWallet,self.uid).stamina,130)
            self.assertIsNone(session.get(UserGameItem,(self.uid,'CARD_CRYSTAL_STAR_BRONZE')))

    def test_account_daily_reset_override_preserves_old_records(self):
        start = self.service.start(self.payload, 'before-reset')
        self.service.finish(start['userQuestResultId'], self.win(start))
        with self.app.state.session_factory() as session:
            self.assertEqual(self.service.daily(session, 512001)['dailyClearCount'], 1)
            reset_at = (self.time + timedelta(minutes=1)).isoformat()
            self.service.update_player_state(session, dailyCountResetAt=reset_at)
            session.commit()
        self.time = self.time + timedelta(minutes=1)
        with self.app.state.session_factory() as session:
            self.assertEqual(self.service.daily(session, 512001)['dailyClearCount'], 0)
        after = self.service.start(self.payload, 'after-reset')
        self.service.finish(after['userQuestResultId'], self.win(after))
        with self.app.state.session_factory() as session:
            self.assertEqual(self.service.daily(session, 512001)['dailyClearCount'], 1)

    def test_daily_limit_and_next_day(self):
        for index in range(10):
            start=self.service.start(self.payload,'battle-%s'%index)
            self.service.finish(start['userQuestResultId'],self.win(start))
        with self.assertRaises(BattleError):
            self.service.start(self.payload,'limit-reached')
        self.time=datetime.fromisoformat('2026-10-22T00:00:00+09:00')
        self.assertEqual(self.service.start(self.payload,'tomorrow')['resultCode'],'success')

    def test_original_protocol_no_header_and_conflicting_retry(self):
        start=self.client.post('/api/battle/start',json=self.payload)
        self.assertEqual(start.status_code,200,start.text)
        again=self.client.post('/api/battle/start',json=self.payload)
        self.assertEqual(start.json(),again.json())
        result=self.win(start.json())
        self.service.finish(start.json()['userQuestResultId'],result)
        with self.assertRaises(BattleError):
            self.service.finish(start.json()['userQuestResultId'],{'result':'RETIRE'})

    def test_invalid_result_cannot_grant_or_close_battle(self):
        import copy
        start=self.service.start(self.payload,'checks')
        for key,value in [('defeatCount',15),('defeatCount',True),
                          ('battleResultDetailData',None),('isAchieveMission2',False),
                          ('isRetryWeakened',True),('isAchieveMission3',False)]:
            result=copy.deepcopy(self.win(start)); result[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(BattleError):
                self.service.finish(start['userQuestResultId'],result)
        with self.app.state.session_factory() as session:
            self.assertEqual(session.get(LocalBattle,start['userQuestResultId']).status,'ACTIVE')
            self.assertEqual(session.get(UserWallet,self.uid).free_sakuradite,300)

    def test_finished_start_id_cannot_launch_again(self):
        start=self.service.start(self.payload,'once')
        self.service.finish(start['userQuestResultId'],{'result':'RETIRE'})
        with self.assertRaises(BattleError):
            self.service.start(self.payload,'once')

    def test_native_a_b_ranks_and_retirement_with_null_report(self):
        for rank,defeats in [('B',13),('A',15)]:
            start=self.service.start(self.payload,'rank-'+rank)
            result=self.win(start);result.update(clearRank=rank,defeatCount=defeats)
            reply=self.service.finish(start['userQuestResultId'],result)
            self.assertEqual(reply['userQuestList'][0]['bestQuestRank'],rank)
        start=self.service.start(self.payload,'retired')
        reply=self.service.finish(start['userQuestResultId'],{'result':'RETIRED',
            'battleResultDetailData':None, 'dropIdList':[], 'clearRank':'NOT_ACHIEVED'})
        self.assertEqual(reply['battleResult']['rewardList'],[])

    def test_interrupted_battle_survives_engine_restart_and_explicit_retire(self):
        start=self.service.start(self.payload,'interrupted')
        self.app.state.engine.dispose()
        reopened=create_app(self.db,ROOT/'fixtures/gacha_1005.json',masterdata_dir=MASTER)
        client=TestClient(reopened)
        try:
            active=client.get('/api/local/page-state').json()['localActiveBattle']
            self.assertEqual(active['userQuestResultId'],start['userQuestResultId'])
            payload={'userQuestResultId':active['userQuestResultId']}
            reply=client.post('/api/local/battle/retire',json=payload)
            self.assertEqual(reply.status_code,200,reply.text)
            self.assertEqual(reply.json(),client.post('/api/local/battle/retire',json=payload).json())
            self.assertIsNone(client.get('/api/local/page-state').json()['localActiveBattle'])
        finally:
            client.close();reopened.state.engine.dispose()

    def unlock_skip(self):
        start = self.service.start(self.payload,'unlock-skip')
        self.service.finish(start['userQuestResultId'],self.win(start))
        self.time = datetime.fromisoformat('2026-10-26T12:00:00+09:00') # Monday bonus
        with self.app.state.session_factory() as session:
            session.get(UserWallet,self.uid).skip_tickets = 1
            session.add(UserGameItem(user_id=self.uid,item_id='SKIP_QUEST',quantity=2))
            session.commit()

    def test_skip_gates_atomicity_concurrency_and_ticket_sources(self):
        with self.assertRaises(BattleError):
            self.service.skip(self.payload,'locked')
        self.unlock_skip()
        before = self.client.get('/api/local/state').json()
        self.assertEqual(before['skipTickets'],3)
        with patch.object(Session,'commit',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):
                self.service.skip(self.payload,'fault')
        self.assertEqual(before,self.client.get('/api/local/state').json())
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(lambda _:self.service.skip(self.payload,'same-skip'),range(6)))
        self.assertTrue(all(r==replies[0] for r in replies))
        reply = replies[0]
        self.assertEqual(reply['userDailyQuestList'][0]['dailyClearCount'],1)
        skip_item_rows = [row for row in reply['userItemList']
                         if row['itemId']=='SKIP_QUEST']
        self.assertEqual(len(skip_item_rows),1)
        self.assertEqual(skip_item_rows[0]['quantity'],1)
        self.assertEqual(sum(r['num'] for r in reply['battleResult']['rewardList']
                             if r['code']=='CARD_CRYSTAL_STAR_BRONZE'),64)
        self.assertFalse(any(r['code'] in ('PRESENTED_MONEY','LIMIT_BREAK_RANK_2')
                             for r in reply['battleResult']['rewardList']))
        after = self.client.get('/api/local/state').json()
        self.assertEqual(after['stamina'],before['stamina']-10)
        self.assertEqual(after['skipTickets'],2)
        self.assertEqual(after['gameItems']['SKIP_QUEST'],1)
        self.assertEqual(after['freeSakuradite'],before['freeSakuradite'])
        with self.assertRaises(BattleError):
            self.service.finish(reply['userQuestResultId'],{'result':'RETIRE'})
        with self.assertRaises(BattleError):
            self.service.start(self.payload,'same-skip')
        with self.assertRaises(BattleError):
            self.service.skip({**self.payload,'deckType':'MAIN2'},'same-skip')
        self.service.skip(self.payload,'second-skip')
        self.service.skip(self.payload,'third-skip')
        with self.assertRaises(BattleError):
            self.service.skip(self.payload,'fourth-skip')
        with self.app.state.session_factory() as session:
            self.assertEqual(session.get(UserWallet,self.uid).skip_tickets,0)
            self.assertEqual(session.get(UserGameItem,(self.uid,'SKIP_QUEST')).quantity,0)
            self.assertEqual(session.get(LocalBattleProgress,(self.uid,0)).state['experience'],32)

    def test_skip_defaults_missing_body_formation_and_is_idempotent(self):
        self.unlock_skip()
        before = self.client.get('/api/local/state').json()
        headers = {'X-Request-Id': 'default-skip'}
        first = self.client.post('/api/battle/skip', headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['resultCode'], 'success')
        retry = self.client.post('/api/battle/skip', json={}, headers=headers)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json(), first.json())
        after = self.client.get('/api/local/state').json()
        self.assertEqual(after['stamina'], before['stamina'] - 10)
        self.assertEqual(
            after['gameItems'].get('SKIP_QUEST', 0),
            before['gameItems'].get('SKIP_QUEST', 0) - 1)
        self.assertEqual(
            first.json()['userDailyQuestList'][0]['dailyClearCount'], 1)

    def test_skip_api_restart_and_active_battle_protection(self):
        self.unlock_skip()
        before = self.client.get('/api/local/state').json()
        self.assertEqual(self.client.post('/api/battle/skip',json={**self.payload,'questId':True},
            headers={'X-Request-Id':'bad-type'}).status_code,422)
        foreign = self.client.post('/api/battle/skip',json={
            **self.payload, 'userCardIdList': ['foreign']},
            headers={'X-Request-Id': 'foreign'})
        self.assertEqual(foreign.status_code, 200)
        self.assertEqual(foreign.json()['resultCode'], 'error')
        self.assertEqual(before,self.client.get('/api/local/state').json())
        active = self.service.start(self.payload,'active')
        with self.assertRaises(BattleError):
            self.service.skip(self.payload,'active-skip')
        self.service.finish(active['userQuestResultId'],{'result':'RETIRE'})
        self.time = datetime.fromisoformat('2026-10-27T12:00:00+09:00')
        first = self.client.post('/api/battle/skip',json=self.payload,headers={'X-Request-Id':'http-skip'})
        self.assertEqual(first.status_code,200,first.text)
        skip_status_ids={row['statusId'] for row in first.json()['userStatusList']}
        self.assertTrue({
            'ACP','MAX_ACP','MAX_DECK','MAX_FRIEND','UEP','MAX_UEP',
            'BTP','MAX_BTP'} <= skip_status_ids)
        after = self.client.get('/api/local/state').json()
        self.app.state.engine.dispose()
        reopened=create_app(self.db,ROOT/'fixtures/gacha_1005.json',masterdata_dir=MASTER)
        client=TestClient(reopened)
        try:
            retry=client.post('/api/battle/skip',json=self.payload,headers={'X-Request-Id':'http-skip'})
            self.assertEqual(retry.json(),first.json())
            self.assertEqual(client.get('/api/local/state').json(),after)
            self.assertEqual(client.get('/api/local/page-state').json()['skipTickets'],2)
        finally:
            client.close();reopened.state.engine.dispose()

    def test_uncaptured_daily_skip_uses_normalized_limit_10(self):
        payload = {**self.payload, 'questId': 511001}
        with self.app.state.session_factory() as session:
            state = self.service.initial_progress(511001)
            state.update(bestQuestRank='S', clearedMission1=True,
                         clearedMission2=True, clearedMission3=True)
            session.add(LocalBattleProgress(
                user_id=self.uid, quest_id=511001, state=state))
            session.get(UserWallet,self.uid).skip_tickets = 10
            session.commit()
        for index in range(10):
            reply = self.service.skip(payload, 'uncaptured-skip-%s' % index)
            self.assertEqual(reply['userDailyQuestList'][0]['dailyClearCount'],
                             index + 1)
        with self.assertRaises(BattleError):
            self.service.skip(payload, 'uncaptured-skip-limit')

    def test_uncaptured_daily_enhancement_stage_settles_maximum_drop(self):
        quest_id = 511003
        payload = {**self.payload, 'questId': quest_id}
        before = self.client.get('/api/local/page-state').json()
        before_quantity = int(before['gameItems'].get('EXP_PP', 0))
        self.assertEqual(len(before['userDailyQuestList']), 6)
        start = self.service.start(payload, 'daily-511003')
        quest = start['battle']['questData']
        self.assertEqual(quest['questType'], 'DAILY')
        self.assertEqual(quest['enemyNum'], 50)
        events = quest['waveData'][0]['waveEventData']
        self.assertEqual(len(events), 50)
        self.assertTrue(all(event.get('dropId') for event in events))
        reply = self.service.finish(
            start['userQuestResultId'], self.win(start))
        exp_rewards = [row for row in reply['battleResult']['rewardList']
                       if row['code']=='EXP_PP']
        self.assertEqual(len(exp_rewards), 100)
        self.assertTrue(all(row['num']==1 for row in exp_rewards))
        self.assertEqual(reply['userDailyQuestList'][0]['dailyTypeName'],
                         'GOLD_CARD_EXP')
        self.assertEqual(reply['userDailyQuestList'][0]['dailyClearCount'], 1)
        after = self.client.get('/api/local/page-state').json()
        self.assertEqual(after['gameItems']['EXP_PP'], before_quantity + 100)
        self.assertEqual(len(after['userDailyQuestList']), 6)
        self.assertIn(quest_id, {row['questId'] for row in after['userQuestList']})
        detail = self.client.get(
            '/api/local/battle-catalog/%s' % quest_id)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['daily']['waveEventCount'], 50)
        self.assertEqual(detail.json()['daily']['dropSlotsPerEnemy'], 2)


if __name__=='__main__':
    unittest.main()
