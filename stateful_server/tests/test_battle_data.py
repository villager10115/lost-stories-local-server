"""Compare adapters against the retained official native DTO, not our output."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from cgls.battle_data import BattleData, BattleError
from cgls.battle_validation import validate_battle

ROOT = Path(__file__).resolve().parents[1]
MASTER = Path('D:/LostStories_Offline/assets/masterdata')


class NativeBattleDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = BattleData(MASTER)
        cls.reference = json.loads((ROOT/'fixtures/battle_native_reference.json').read_text('utf8'))

    def pair(self, index):
        p = self.reference['pilots'][index]
        k = self.reference['kmfs'][index]
        n = p['native']
        weapon = self.data.weapons[k['native']['knightmareId']]
        pilot = SimpleNamespace(user_card_id='pilot', mst_pilot_id=n['pilotId'],
            level=n['level'], awakening_level=p['revision'], limit_break=p['limitBreak'],
            unlocked_feature_ids=[], skill_levels=[1,1])
        kmf = SimpleNamespace(user_kmf_id='kmf', customization_id=weapon['knightmareFrameCustomizeId'],
            mst_kmf_id=weapon['knightmareFrameId'], revision=k['revision'] or 0,
            revision_class=k['native']['awakeRankFrameNo'])
        return pilot, kmf

    def test_official_pilots_features_and_transform_tables(self):
        for index, sample in enumerate(self.reference['pilots']):
            with self.subTest(pilot=sample['native']['pilotId']):
                dto = self.data.assemble([self.pair(index)],{}, player_sex=sample['native'].get('sex','MALE'))['playerData']
                actual = dto['pilotStatusData'][0]
                for key,value in sample['native'].items():
                    if key in ('pilotSkillLevel1','pilotSkillLevel2'):
                        # This fixture omits the official account's skill and
                        # attribute-rank bonuses; do not infer them from output.
                        continue
                    self.assertEqual(actual.get(key),value,key)
                for table,key in [('pilotSkillData','pilotSkillId'),('knightmareSkillData','knightmareSkillId'),
                                  ('knightmareFeatureSkillData','kmfFeatureSkillId'),('transformDetailData','id')]:
                    expected={r[key]:r for r in self.reference['tables'][table]}
                    for row in dto[table]:
                        if row[key] in expected:
                            for field,value in expected[row[key]].items():
                                self.assertEqual(row.get(field),value,(table,row[key],field))

    def test_captured_519001_wave_dto_is_selected_independently(self):
        battle = self.data.assemble([self.pair(0)],{},quest_id=519001)
        quest = battle['questData']
        self.assertEqual(quest['questId'],519001)
        self.assertEqual(quest['mapDataNo'],1022001)
        self.assertEqual(quest['enemyNum'],20)
        self.assertEqual(len(quest['waveData'][0]['waveEventData']),20)
        self.assertEqual(sum('dropId' in event for event in quest['waveData'][0]['waveEventData']),8)
        self.assertEqual(quest['fieldData']['fieldId'],1022)

    def test_catalog_story_fallback_uses_enumerated_enemies_and_late_boss(self):
        battle = self.data.assemble([self.pair(0)],{},quest_id=101120)
        quest = battle['questData']
        events = quest['waveData'][0]['waveEventData']
        self.assertEqual(quest['questId'],101120)
        self.assertEqual(quest['mapDataNo'],1001031)
        self.assertEqual(quest['enemyNum'],18)
        self.assertEqual(len(events),18)
        self.assertEqual(events[-1]['npcId'],400002)
        self.assertEqual(events[-1]['timeMilliSeconds'],105000)
        self.assertEqual(events[-1]['parameters1'],'1')
        boss=next(r for r in quest['npcStatusData'] if r['npcId']==400002)
        self.assertTrue(boss['isBoss'])
        self.assertTrue(boss['isOneOnOne'])

    def test_story_battle_plugin_status_and_fail_closed_conditions(self):
        status=self.data.story_catalog_status()
        self.assertEqual(status['storyBattleCount'],858)
        self.assertEqual(status['tutorialBattleCount'],1)
        self.assertEqual(status['additionalBattleCount'],3079)
        self.assertEqual(status['battleCount'],3938)
        self.assertEqual(status['supportedCount'],3845)
        self.assertEqual(status['rejectedCount'],93)
        self.assertEqual(status['battleCountByQuestType']['CHALLENGE'],546)
        self.assertEqual(status['battleCountByQuestType']['EXPEDITION'],2241)
        self.assertEqual(status['battleCountByQuestType']['ANOTHER_CHARA'],14)
        self.assertEqual(status['battleCountByQuestType']['ENTANGLE_CHALLENGE'],112)
        self.assertEqual(status['battleCountByQuestType']['SIDE_CHALLENGE'],70)
        self.assertEqual(status['battleCountByQuestType']['STRATEGIC_COMMAND'],30)
        self.assertIn('RootEntangleTop',status['pageCoverage']['implemented'])
        self.assertIn('ChallengeQuestTop',
                      status['pageCoverage']['missingPageDefinitions'])
        self.assertFalse(self.data.story_quest_status(733002)['supported'])
        self.assertEqual(self.data.story_quest_status(733002)['reason'],
                         'BOSS_ONLY_WAVE_UNRESOLVED')
        self.assertIn(1000,status['supportedQuestIds'])
        self.assertIn(418101,status['supportedQuestIds'])
        self.assertTrue(self.data.story_quest_status(418101)['supported'])
        unsupported=self.data.story_quest_status(304104)
        self.assertFalse(unsupported['supported'])
        self.assertEqual(unsupported['reason'],'UNSUPPORTED_WIN_CONDITION_5')
        with self.assertRaisesRegex(BattleError,'UNSUPPORTED_WIN_CONDITION_5'):
            self.data.assemble([self.pair(0)],{},quest_id=304104)

    def test_catalog_chain_and_enemy_mechanics_are_complete(self):
        detail=self.data.battle_catalog_detail(101101)
        self.assertTrue(detail['status']['supported'])
        self.assertGreater(detail['chapter']['battleCount'],0)
        self.assertIsInstance(detail['chapter']['battleIndex'],int)
        self.assertIsNotNone(detail['globalNextBattle'])
        battle=self.data.assemble([self.pair(0)],{},quest_id=101120)
        quest=battle['questData']
        range_ids={row['attackRangeId'] for row in quest['npcAttackRangeData']}
        skill_ids={row['knightmareSkillId'] for row in quest['npcKnightmareSkillData']}
        for npc in quest['npcStatusData']:
            self.assertIn(npc['attackRangeId'],range_ids)
            if npc['knightmareSkillId']:
                self.assertIn(npc['knightmareSkillId'],skill_ids)
        validate_battle(battle)

    def test_every_supported_catalog_battle_builds_before_launch(self):
        status=self.data.story_catalog_status()
        for quest_id in status['supportedQuestIds']:
            with self.subTest(questId=quest_id):
                battle=self.data.assemble([self.pair(0)],{},quest_id=quest_id)
                validate_battle(battle)

    def test_activity_quest_types_and_placed_gimmicks_build(self):
        samples={810101:'ANOTHER_CHARA',600801:'EXPEDITION',
                 941013:'SIDE',916801:'EVENT',962101:'ENTANGLE',
                 901001:'ANOTHER_SIDE'}
        for quest_id,quest_type in samples.items():
            with self.subTest(questId=quest_id):
                battle=self.data.assemble([self.pair(0)],{},quest_id=quest_id)
                self.assertEqual(battle['questData']['questType'],quest_type)
                validate_battle(battle)
        gimmick=self.data.assemble([self.pair(0)],{},quest_id=602107)
        quest=gimmick['questData']
        self.assertIn(3700,{row['gimmickId'] for row in quest['gimmickData']})
        self.assertEqual(len(quest['placedGimmickData']),36)
        self.assertIn(110,{row['attackRangeId'] for row in quest['gimmickRangeData']})
        validate_battle(gimmick)

    def test_condition_three_is_supported_with_same_invasion_rank(self):
        status=self.data.story_quest_status(101125)
        self.assertTrue(status['supported'])
        self.assertEqual(status['winConditionId'],3)
        self.assertEqual(status['winConditionCode'],
                         'INVADED_DESTROY_ALL_BOSS_2')

    def test_entangle_constraints_and_max_card_stats(self):
        quest=self.data.story_quest(961201)
        constraints=quest['catalogConstraints']
        self.assertIn('102001',constraints['battleParameters'].split(','))
        self.assertEqual(constraints['questDeckConditionCode'],
                         'DESIGNATION_AFFILIATION')
        pilot=SimpleNamespace(user_card_id='event-pilot',mst_pilot_id=102001,
            level=1,awakening_level=0,limit_break=0,
            unlocked_feature_ids=[],skill_levels=[1,1])
        kmf=SimpleNamespace(user_kmf_id='event-kmf',customization_id=100101,
            mst_kmf_id=1001,revision=0,revision_class=1)
        battle=self.data.assemble([(pilot,kmf)],{},quest_id=961201)
        row=battle['playerData']['pilotStatusData'][0]
        self.assertEqual(row['level'],60)
        self.assertEqual(row['awakeRankFrameNo'],6)
        validate_battle(battle)

    def test_official_kmf_stats_and_deployment_delays(self):
        for index,sample in enumerate(self.reference['kmfs']):
            dto=self.data.assemble([self.pair(index)],{})['playerData']['knightmareStatusData'][0]
            for key,value in sample['native'].items():
                if sample['revision'] is None and key in ('attackPoint','defensePoint','sortieCost',
                                                          'maxBlockingCount','knightmareSkillLevel'):
                    continue # No captured revision exists for these variable stats.
                self.assertEqual(dto.get(key),value,(sample['native']['knightmareId'],key))

    def test_extra_skill_slots_follow_their_named_parent_and_have_gimmicks(self):
        pilot,kmf=self.pair(0)
        pilot.mst_pilot_id=103048
        pilot.level=1;pilot.awakening_level=0;pilot.limit_break=0
        battle=self.data.assemble([(pilot,kmf)],{})
        row=battle['playerData']['pilotStatusData'][0]
        self.assertEqual([row['pilotSkillParentIndex%s'%i] for i in (3,4,5)],[1,1,1])
        pilot.mst_pilot_id=101056
        battle=self.data.assemble([(pilot,kmf)],{})
        self.assertIn(3021,{r['gimmickId'] for r in battle['questData']['gimmickData']})
        self.assertIn(1,{r['affectorCodeGroupId'] for r in battle['playerData']['affectorCodeGroupData']})

    def test_basic_and_unarmed_frames_do_not_require_a_fabricated_skill(self):
        pilot,kmf=self.pair(0)
        for wid in (120101,):
            kmf.customization_id=wid
            kmf.mst_kmf_id=self.data.weapons[wid]['knightmareFrameId']
            kmf.revision=0
            dto=self.data.assemble([(pilot,kmf)],{})['playerData']
            self.assertEqual(dto['knightmareStatusData'][0]['knightmareSkillId'],0)
            self.assertNotIn(0,{r['knightmareSkillId'] for r in dto['knightmareSkillData']})
            self.assertEqual(dto['knightmareSkillData'],[])

    def test_unlocated_extended_transform_is_not_silently_dropped(self):
        pilot,kmf=self.pair(0)
        for wid in (700101,700201,710101):
            kmf.customization_id=wid;kmf.mst_kmf_id=self.data.weapons[wid]['knightmareFrameId'];kmf.revision=0
            with self.subTest(weapon=wid),self.assertRaisesRegex(BattleError,'extended transform: 1003'):
                self.data.assemble([(pilot,kmf)],{})

    def test_union_forms_use_native_detail_links_and_retained_features(self):
        pilot,kmf=self.pair(0)
        for wid,first,second,skill in ((330701,1080,1081,556310),(330201,1260,1261,556364),
                                     (331101,1260,1261,556364),(700301,1090,1091,556320),
                                     (710301,1090,1091,556320)):
            with self.subTest(weapon=wid):
                kmf.customization_id=wid;kmf.mst_kmf_id=self.data.weapons[wid]['knightmareFrameId'];kmf.revision=0
                battle=self.data.assemble([(pilot,kmf)],{})
                dto=battle['playerData'];forms={t['id']:t for t in dto['transformDetailData']}
                self.assertEqual(set(forms),{first,second})
                self.assertEqual(forms[first]['weaponChangeTransformDetailId1'],second)
                self.assertEqual(forms[second]['weaponChangeTransformDetailId1'],first)
                self.assertEqual([forms[n]['knightmareSkillId'] for n in (first,second)],[skill,skill])
                for source in self.data.weapons[wid]['allowTransformKnightmareFrameList']:
                    target=forms[source['transformKnightmareFrameId']]
                    self.assertEqual(target['attackRangeId'],source['attackRangeId'])
                    self.assertEqual(target['kmfFeatureSkillId2'],source['kmfFeatureSkillId2'])
                forms[second]['weaponChangeTransformDetailId1']=999999
                with self.assertRaisesRegex(BattleError,'union weapon form'):
                    validate_battle(battle)

    def test_unlocated_union_effect_group_still_fails_before_start(self):
        pilot,kmf=self.pair(0);kmf.customization_id=102401;kmf.mst_kmf_id=1024;kmf.revision=0
        with self.assertRaisesRegex(BattleError,'Missing status effect group 20'):
            self.data.assemble([(pilot,kmf)],{})

    def test_story_npc_kmf_skill_and_dependencies_are_preserved(self):
        battle=self.data.assemble([self.pair(0)],{},quest_id=418101)
        quest=battle['questData']
        npc=next(row for row in quest['npcStatusData'] if row['npcId']==210003)
        self.assertEqual(npc['knightmareSkillId'],556239)
        self.assertEqual(npc['knightmareSkillLevel'],1)
        self.assertTrue(npc['canAutoInvokeKnightmareFrameSkill'])
        skill=next(row for row in quest['npcKnightmareSkillData']
                     if row['knightmareSkillId']==556239)
        self.assertEqual([skill['affectorId1'],skill['affectorId2']],[5553,2010])
        self.assertTrue(skill['entrainmentFlag1'])
        self.assertEqual(skill['attackRangeId'],242)
        effects={row['affectorId']:row for row in quest['npcAffectorData']}
        self.assertEqual(effects[5553]['affectorCode'],'DAMAGE_MULTIPLY_ATTACK')
        self.assertEqual(effects[2010]['affectorCode'],'HASTE')
        self.assertIn(1,{row['priorityId'] for row in quest['npcPriorityData']})
        self.assertIn(242,{row['attackRangeId'] for row in quest['npcAttackRangeData']})

    def test_battle_catalog_detail_traces_both_sides_and_missing_story(self):
        middle=self.data.battle_catalog_detail(417102)
        self.assertEqual(middle['previousBattle']['questId'],417101)
        self.assertEqual(middle['nextBattle']['questId'],417103)
        self.assertEqual(middle['requiredQuest']['questId'],417101)
        self.assertTrue(all(row['found'] for row in middle['requiredChain']))
        current=self.data.battle_catalog_detail(418101)
        self.assertEqual(current['globalPreviousBattle']['questId'],417201)
        self.assertFalse(current['previousOnlyStoryQuest']['found'])
        self.assertEqual(current['previousOnlyStoryQuest']['questId'],417013)
        tutorial=self.data.battle_catalog_detail(1000)
        self.assertTrue(tutorial['status']['supported'])
        self.assertEqual(tutorial['quest']['activeTutorialId'],'TU0401')
        self.assertEqual(tutorial['globalNextBattle']['questId'],101101)
        self.assertIsNone(self.data.battle_catalog_detail(999999))

    def test_every_daily_stage_has_validated_units_waves_and_maximum_drops(self):
        quests = self.data.daily_quests()
        self.assertEqual(len(quests), 30)
        self.assertEqual(len(self.data.daily_type_quests()), 6)
        status = self.data.story_catalog_status()
        self.assertEqual(status['dailyBattleCount'], 30)
        self.assertEqual(status['dailyTypeCount'], 6)
        self.assertEqual(status['dailyDropPolicy'],
                         'MAX_EACH_LOTTERY_ENTRY_PER_ENEMY')
        for quest in quests:
            quest_id = quest['questId']
            with self.subTest(questId=quest_id):
                battle = self.data.assemble(
                    [self.pair(0)], {}, quest_id=quest_id)
                validate_battle(battle)
                events = battle['questData']['waveData'][0]['waveEventData']
                self.assertEqual(len(events), quest['enemyNum'])
                self.assertEqual(
                    {event['npcId'] for event in events},
                    set(quest['uniqueEnemyNpcIdList']))
                bundle = self.data.daily_reward_bundle(quest_id)
                self.assertTrue(bundle)
                self.assertEqual(
                    [row['code'] for row in bundle],
                    [row['genericCode'] for row in
                     quest['uniqueQuestDropRewardList']
                     if row['genericCode'] != 'MISS'])
                expected = {}
                for row in bundle:
                    expected[row['code']] = (
                        expected.get(row['code'], 0) +
                        row['num'] * quest['enemyNum'])
                maximum = {
                    row['code']: row['num']
                    for row in self.data.daily_max_rewards(quest_id)}
                self.assertEqual(maximum, expected)

    def test_daily_catalog_detail_exposes_reset_wave_and_enemy_policy(self):
        detail = self.data.battle_catalog_detail(519002)
        self.assertEqual(detail['quest']['questType'], 'DAILY')
        self.assertTrue(detail['status']['supported'])
        daily = detail['daily']
        self.assertEqual(daily['resetTimeZone'], 'Asia/Tokyo')
        self.assertEqual(daily['maxClearCount'], 10)
        self.assertEqual(daily['maxAdditionalCount'], 10)
        self.assertEqual(daily['waveEventCount'], 34)
        self.assertEqual(daily['dropSlotsPerEnemy'], 2)
        self.assertEqual(daily['dropPolicy'],
                         'MAX_EACH_LOTTERY_ENTRY_PER_ENEMY')
        self.assertTrue(daily['enemyPool'])
        self.assertEqual(
            {row['code']: row['num'] for row in daily['maxClearRewards']},
            {'KMF_CHIP_FAR_SILVER': 68})


if __name__=='__main__':
    unittest.main()
