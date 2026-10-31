"""Build native battle DTOs from local ownership and preserved master definitions."""
import copy
from collections import Counter
import json
import math
import re
from pathlib import Path

from .kmf_color import custom_color_state


class BattleError(ValueError):
    pass

DAILY_MAX_DROP_POLICY = 'MAX_EACH_LOTTERY_ENTRY_PER_ENEMY'


GROWTH = {
    'NEAR_ATTACK': (1.5, .5, .8, .8), 'NEAR_DEFENSE': (.8, .5, 1.1, 1.5),
    'NEAR_BALANCE': (1.2, .5, 1, 1), 'FAR_ATTACK': (.5, 1.5, .8, .8),
    'FAR_DEFENSE': (.5, .8, 1.1, 1.5), 'FAR_BALANCE': (.5, 1.2, 1, 1),
    'BALANCE_ATTACK': (1.2, 1.2, .8, .8), 'BALANCE_DEFENSE': (.8, .8, 1.2, 1.2),
    'BALANCE_BALANCE': (1.1, 1.1, 1.1, 1.1),
}
STAT_CODES = {'HP':'hp', 'DEFENSE_ADJUST':'defenseAdjust', 'AVOID_RATE':'avoidRate',
    'BLOCK_NUM':'blockNum', 'NEAR_ATTACK_ADJUST':'nearAttackAdjust',
    'NEAR_HIT_ACCURACY':'nearHitAccuracy', 'NEAR_ATTACK_INTERVAL':'nearAttackInterval',
    'FAR_ATTACK_ADJUST':'farAttackAdjust', 'FAR_HIT_ACCURACY':'farHitAccuracy',
    'FAR_ATTACK_INTERVAL':'farAttackInterval', 'COST':'cost', 'RELOCATION_TIME':'relocationTime',
    'ATTACK':'attack', 'DEFENSE':'defense', 'ATTACK_ALL':'attack', 'DEFENSE_ALL':'defense',
    'COST_ALL':'cost', 'BLOCK_NUM_ALL':'blockNum'}


def boosts(definition, revision, level=0):
    result = []
    for index in range(1, revision + 1):
        row = definition.get('revisionGroup', {}).get('revision%s' % index)
        if row is None:
            raise BattleError('Missing revision definition')
        for number in range(1, 5):
            if row.get('boostCode%s' % number):
                result.append((row['boostCode%s' % number], row['boostValue%s' % number]))
    result.extend((r['boostCode'], r['value']) for r in
                  definition.get('cardLevelBonus', {}).get('boostList', []) if r['level'] <= level)
    return result


def pilot_stats(card, level, revision):
    stats = {key: card[key] for key in set(STAT_CODES.values()) if key in card}
    near, far, hp, defense = GROWTH[card['growthType']]
    factor = (level - 1) / 98 * 2.3
    for key, growth in [('nearAttackAdjust', near), ('farAttackAdjust', far),
                        ('hp', hp), ('defenseAdjust', defense)]:
        stats[key] += card[key] * (10 * factor) * (10 * growth) / 100
    for code, value in boosts(card, revision, level):
        if code in STAT_CODES:
            key = STAT_CODES[code]
            stats[key] += int(value)
    stats = {key: math.floor(value) for key, value in stats.items()}
    # Same displayed strength calculation retained by DeckFormation/CardUtil.
    side = 'near' if stats['nearAttackAdjust'] >= stats['farAttackAdjust'] else 'far'
    score = (int(300 * stats[side+'AttackAdjust'] / 1000) * int(1 + 1000 / stats[side+'AttackInterval'])
             + int(stats['defenseAdjust'] / 10) + int(stats['hp'] / 3))
    stats['strength'] = int(score * int(1 + .02 * max(stats['blockNum']-1, 0)) /
                            max(max(stats['cost'], 0) ** (1/3), 1))
    return stats


def pilot_skills(card, pilot):
    levels = list(pilot.skill_levels or [1, 1]) + [1] * 6
    for code, value in boosts(card, pilot.awakening_level, pilot.level):
        if code == 'CARD_SKILL_LEVEL_UP':
            index, amount = map(int, value.split(','))
            levels[index - 1] += amount
    result = {}
    for number in range(1, 7):
        if not card.get('cardSkillId%s' % number):
            continue
        unlock = card.get('unlockCardSkillLevel%s' % number, 0)
        result['cardSkillLevel%s' % number] = levels[number - 1] if number <= 2 else 1
        result['cardSkillLocked%s' % number] = bool(card.get('cardSkillLocked%s' % number) and pilot.level < unlock)
    return result


def kmf_stats(weapon, revision):
    stats = {key: weapon[key] for key in ('cost', 'blockNum', 'attack', 'defense')}
    stats['skillLevel'] = 1
    for code, value in boosts(weapon, revision):
        if code in STAT_CODES and STAT_CODES[code] in stats:
            stats[STAT_CODES[code]] += int(value)
        elif code == 'KMF_SKILL_LEVEL_UP':
            stats['skillLevel'] += int(value)
    target = 5 if weapon['attackType'] == 'ALL' else int(weapon['attackType'])
    # Unarmed support frames and F.L.E.I.J.A. explicitly use empty range 999.
    distance = max((r['index'] for r in json.loads(weapon['attackRange']['attackRange'])), default=0)
    score = stats['attack'] + stats['defense']/3 * int(1+.02*max(stats['blockNum']-1,0)) * int(1+.1*max(target-1,0)) * int(1+.02*distance)
    stats['strength'] = int(score / max(max(stats['cost'],0) ** (1/3), 1))
    return stats


class BattleData:
    def __init__(self, masterdata):
        if not masterdata:
            raise BattleError('Battle master data is not configured')
        self.masterdata = Path(masterdata)
        self.master = json.loads((Path(masterdata) / 'pages/MyPage.static.json').read_text('utf8'))
        self.cards = {r['cardId']: r for r in self.master['cardList']}
        self.characters = {r['charaId']: r for r in self.master['charaList']}
        self.kmfs = {r['knightmareFrameId']: r for r in self.master['knightmareFrameList']}
        self.weapons = {r['knightmareFrameCustomizeId']: r for r in self.master['knightmareFrameCustomizeList']}
        self.daily_master = json.loads((Path(masterdata) / 'pages/DailyQuestTop.static.json').read_text('utf8'))
        self.gimmicks = {r['gimmickId']: r for r in self.daily_master['gimmickList']}
        self.npcs = {r['npcId']: r for r in self.daily_master['npcList']}
        fixture_root = Path(__file__).resolve().parents[1] / 'fixtures'
        self.fixtures = {}
        for path in fixture_root.glob('battle_*.json'):
            match = re.fullmatch(r'battle_(\d+)\.json', path.name)
            if match:
                self.fixtures[int(match.group(1))] = json.loads(
                    path.read_text('utf8'))
        if 512001 not in self.fixtures:
            raise BattleError('Missing captured 512001 battle fixture')
        self.fixture = self.fixtures[512001]
        self.story_catalog_path = fixture_root / 'main_story_catalog.json'
        self.tutorial_catalog_path = fixture_root / 'tutorial_quests.json'
        self._external_catalog = None
        self.quest_catalog_path = fixture_root / 'all_quest_catalog.json'
        self._story_catalog = None
        self._tutorial_catalog = None
        self._quest_catalog = None
        self._daily_quest_rows = None
        self._daily_quest_index = None
        self._story_fixture_cache = {}
        self.story_plugin = json.loads(
            (fixture_root / 'story_battle_plugin.json').read_text('utf8'))

    @property
    def story_catalog(self):
        if self._story_catalog is None:
            self._story_catalog = json.loads(self.story_catalog_path.read_text('utf8'))
        return self._story_catalog

    @property
    def quest_catalog(self):
        if self._quest_catalog is None:
            if self.quest_catalog_path.is_file():
                self._quest_catalog = json.loads(
                    self.quest_catalog_path.read_text('utf8'))
            else:
                self._quest_catalog = {'quests': []}
        return self._quest_catalog

    def story_quest(self, quest_id):
        return next((row for row in self.all_story_quests()
                    if row['questId'] == quest_id), None)

    def catalog_quest(self, quest_id):
        return next((row for row in self.catalog_quests()
                    if row['questId'] == quest_id), None)

    def catalog_quests(self):
        rows = list(self.quest_catalog.get('quests', []))
        if not rows:
            rows = list(self.story_catalog['quests'])
        tutorial_ids = {row['questId']
                        for row in self.tutorial_catalog['quests']}
        rows = [row for row in rows if row['questId'] not in tutorial_ids]
        rows.extend(self.tutorial_catalog['quests'])
        constraints = {row['questId']: row for row in
                       self.external_catalog['deckOnlyQuests']}
        if constraints:
            rows = [({**row, 'catalogConstraints': copy.deepcopy(
                constraints[row['questId']])}
                if row['questId'] in constraints else row) for row in rows]
        return rows

    def daily_quests(self):
        if self._daily_quest_rows is not None:
            return self._daily_quest_rows
        rows = self.quest_catalog.get('quests', [])
        if not rows:
            rows = self.story_catalog.get('quests', [])
        self._daily_quest_rows = sorted(
            (self._with_daily_limits(copy.deepcopy(row))
             for row in rows if row.get('questType') == 'DAILY'),
            key=lambda row: int(row['questId']),
        )
        return self._daily_quest_rows

    @staticmethod
    def _with_daily_limits(row):
        daily_type = row.get('dailyType')
        if isinstance(daily_type, dict):
            daily_type['maxClearCount'] = 10
            daily_type['maxAdditionalCount'] = 10
        return row

    def daily_quest(self, quest_id):
        if self._daily_quest_index is None:
            self._daily_quest_index = {
                int(row['questId']): row for row in self.daily_quests()}
        return self._daily_quest_index.get(int(quest_id))

    def daily_type_quests(self):
        """Return one representative quest for each daily reward type."""
        result = {}
        for quest in self.daily_quests():
            name = (quest.get('dailyType') or {}).get('name')
            if name and name not in result:
                result[name] = quest
        return result

    def daily_reward_bundle(self, quest_id):
        """Maximum local roll for one validated daily drop event.

        The retained page exposes all possible lottery entries but not the
        server-side RNG implementation. Local maximum mode therefore runs
        every non-MISS reward row. Each row is an independent slot and keeps
        its own quantity. The policy is exposed in catalog diagnostics.
        """
        quest = self.daily_quest(quest_id)
        if quest is None:
            raise BattleError('Quest %s is not a daily battle' % quest_id)
        lottery = {
            reward.get('genericCode'): reward
            for reward in quest.get('questDropLotteryInfoList') or []
            if reward.get('genericCode') not in (None, '', 'MISS')
        }
        bundle = []
        # Each non-MISS row in uniqueQuestDropRewardList is one reward slot.
        # Repeated rows are independent slots, not accidental duplicates.
        for reward in quest.get('uniqueQuestDropRewardList') or []:
            code = reward.get('genericCode')
            if not code or code == 'MISS':
                continue
            lottery_row = lottery.get(code)
            if lottery_row is None:
                raise BattleError(
                    'Daily quest %s has a reward slot without lottery metadata: %s'
                    % (quest_id, code))
            bundle.append({
                'type': (reward.get('presentType') or
                         lottery_row.get('presentType') or 'ITEM'),
                'code': code,
                'num': int(reward.get('num', 1)),
            })
        if not bundle:
            raise BattleError('Daily quest %s has no retained drop lottery' %
                              quest_id)
        return bundle

    def daily_max_rewards(self, quest_id, coefficient=1):
        """Aggregate maximum rewards for one clear."""
        quest = self.daily_quest(quest_id)
        if quest is None:
            raise BattleError('Quest %s is not a daily battle' % quest_id)
        total = Counter()
        kinds = {}
        for reward in self.daily_reward_bundle(quest_id):
            total[reward['code']] += (
                int(reward['num']) * int(quest.get('enemyNum', 0)) *
                float(coefficient))
            kinds[reward['code']] = reward['type']
        return [{
            'type': kinds[code], 'code': code, 'num': int(quantity)
        } for code, quantity in total.items() if quantity > 0]

        rows = list(self.quest_catalog.get('quests', []))
        if not rows:
            rows = list(self.story_catalog['quests'])
        tutorial_ids = {row['questId']
                        for row in self.tutorial_catalog['quests']}
        rows = [row for row in rows if row['questId'] not in tutorial_ids]
        rows.extend(self.tutorial_catalog['quests'])
        constraints = {row['questId']: row for row in
                       self.external_catalog['deckOnlyQuests']}
        if constraints:
            rows = [({**row, 'catalogConstraints': copy.deepcopy(
                constraints[row['questId']])}
                if row['questId'] in constraints else row) for row in rows]
        return rows

    @property
    def tutorial_catalog(self):
        if self._tutorial_catalog is None:
            self._tutorial_catalog = json.loads(
                self.tutorial_catalog_path.read_text('utf8'))
        return self._tutorial_catalog

    def all_story_quests(self):
        return [row for row in self.catalog_quests()
                if not row.get('onlyStory')]

    def tutorial_quests(self):
        return copy.deepcopy(self.tutorial_catalog['quests'])

    @property
    def external_catalog(self):
        if self._external_catalog is not None:
            return self._external_catalog
        pages = self.masterdata / 'pages'
        battle_quests = []
        deck_only = []
        event_stories = []

        quest_top_path = pages / 'QuestTop.static.json'
        if quest_top_path.is_file():
            quest_top = json.loads(quest_top_path.read_text('utf8'))
            for entry in quest_top.get('anotherQuestDetailList', []):
                quest = entry.get('quest')
                if not isinstance(quest, dict) or quest.get('onlyStory'):
                    continue
                if not quest.get('uniqueEnemyNpcIdList'):
                    continue
                row = copy.deepcopy(quest)
                row['catalogSource'] = 'QUEST_TOP_ANOTHER_CHARA'
                for key in ('questBattleConditionCode',
                            'questDeckConditionCode', 'parameters',
                            'questDeckConditionCode2', 'parameters2',
                            'battleParameters'):
                    if entry.get(key) is not None:
                        row[key] = copy.deepcopy(entry[key])
                battle_quests.append(row)

        root_path = pages / 'RootEntangleTop.static.json'
        if root_path.is_file():
            root = json.loads(root_path.read_text('utf8'))
            for entry in root.get('entangleChallengeQuestList', []):
                row = copy.deepcopy(entry)
                row['catalogSource'] = 'ROOT_ENTANGLE_TOP'
                row['questType'] = 'ENTANGLE_CHALLENGE'
                row['definitionState'] = 'DECK_CONSTRAINTS_ONLY'
                deck_only.append(row)

        event_path = pages / 'EventStoryTop.static.json'
        if event_path.is_file():
            event_page = json.loads(event_path.read_text('utf8'))
            for event in event_page.get('eventList', []):
                if event.get('eventType') not in (
                        'STORY', 'STRATEGIC_COMMAND', 'EXPEDITION_AREA'):
                    continue
                row = copy.deepcopy(event)
                row['catalogSource'] = 'EVENT_STORY_TOP'
                event_stories.append(row)

        missing_pages = [
            name for name in (
                'ChallengeQuestTop', 'ExpeditionTop', 'AnotherQuestTop',
                'SideQuestTop', 'EventMultiFrontTop',
                'EventHighStrategicCommandTop')
            if not (pages / (name + '.static.json')).is_file()]

        self._external_catalog = {
            'battleQuests': battle_quests,
            'dailyBattleCount': len(self.daily_quests()),
            'dailyTypeCount': len(self.daily_type_quests()),
            'dailyDropPolicy': DAILY_MAX_DROP_POLICY,
            'deckOnlyQuests': deck_only,
            'eventStories': event_stories,
            'sources': {
                'anotherCharaBattleCount': len(battle_quests),
                'rootEntangleQuestCount': len(deck_only),
                'eventStoryCount': len(event_stories),
                'missingPages': missing_pages,
            }}
        return self._external_catalog

    def is_story_quest(self, quest_id):
        return self.story_quest(quest_id) is not None

    def story_quest_status(self, quest_id):
        quest = self.story_quest(quest_id)
        if quest is None:
            return {'supported': False, 'reason': 'NOT_A_STORY_BATTLE'}
        if not self.story_plugin.get('enabled'):
            return {'supported': False, 'reason': 'PLUGIN_DISABLED'}
        conditions = self.story_plugin['conditions']
        quest_type = quest.get('questType')
        if quest_type not in conditions['supportedQuestTypes']:
            return {'supported': False,
                    'reason': 'UNSUPPORTED_QUEST_TYPE_%s' % quest_type}
        catalog_constraints = quest.get('catalogConstraints') or {}
        battle_condition = catalog_constraints.get('questBattleConditionCode')
        if battle_condition not in (None, 'CARD_LEVEL_REVISION_MAX'):
            return {'supported': False,
                    'reason': 'UNSUPPORTED_BATTLE_CONDITION_%s' % battle_condition}
        deck_codes = {catalog_constraints.get('questDeckConditionCode'),
                      catalog_constraints.get('questDeckConditionCode2')} - {None}
        if not deck_codes <= {'DESIGNATION_AFFILIATION',
                            'DESIGNATION_AFFILIATION_KMF'}:
            return {'supported': False,
                    'reason': 'UNSUPPORTED_DECK_CONDITION_%s' %
                              sorted(deck_codes - {'DESIGNATION_AFFILIATION',
                              'DESIGNATION_AFFILIATION_KMF'})[0]}
        condition_id = int(quest.get('questFinishConditionId', 0))
        if condition_id not in conditions['supportedWinConditionIds']:
            return {'supported': False,
                    'reason': 'UNSUPPORTED_WIN_CONDITION_%s' % condition_id}
        enemy_ids = list(dict.fromkeys(
            quest.get('uniqueEnemyNpcIdList') or []))
        if not enemy_ids:
            return {'supported': False, 'reason': 'EMPTY_ENEMY_POOL'}
        missing = [npc_id for npc_id in enemy_ids if npc_id not in self.npcs]
        if missing:
            return {'supported': False, 'reason': 'UNKNOWN_NPC_%s' % missing[0]}
        if not quest.get('enemyBaseLocations') or not quest.get('allyBaseLocations'):
            return {'supported': False, 'reason': 'MISSING_BASE_LOCATION'}
        enemies = [self.npcs[npc_id] for npc_id in enemy_ids]
        bosses = [npc for npc in enemies
                  if npc.get('bossFlag') or npc.get('oneOnOneFlag')]
        normals = [npc for npc in enemies if npc not in bosses]
        if int(quest.get('enemyNum', 0)) > len(bosses) and not normals:
            return {'supported': False,
                    'reason': 'BOSS_ONLY_WAVE_UNRESOLVED'}
        supported_missions = set(conditions['supportedMissionCodes'])
        for number in (1, 2, 3):
            definition = quest.get('questMission%s' % number) or {}
            code = definition.get('questMissionCode')
            if code and code not in supported_missions:
                return {'supported': False,
                        'reason': 'UNSUPPORTED_MISSION_%s' % code}
        missing_mechanic = self._missing_enemy_mechanic(enemy_ids)
        if missing_mechanic:
            return {'supported': False, 'reason': missing_mechanic}
        if quest.get('questType') == 'TUTORIAL':
            if not quest.get('activeTutorialId'):
                return {'supported': False, 'reason': 'MISSING_ACTIVE_TUTORIAL_ID'}
            processors = {value.strip() for value in
                          str(quest.get('postProcessors') or '').split(',')
                          if value.strip()}
            if processors != {'TUTORIAL_ID_SET'} or not quest.get('postTutorialId'):
                return {'supported': False,
                        'reason': 'UNSUPPORTED_TUTORIAL_POST_PROCESSOR'}
        return {'supported': True, 'reason': None,
                'winConditionId': condition_id,
                'winConditionCode': conditions['winConditionCodeById'][str(condition_id)]}

    def _missing_enemy_mechanic(self, enemy_ids):
        for npc_id in enemy_ids:
            npc = self.npcs[npc_id]
            weapon = self.weapons.get(npc.get('knightmareFrameCustomizeId'))
            if weapon is None:
                return 'UNKNOWN_NPC_WEAPON_%s' % npc_id
            if not weapon.get('attackRange'):
                return 'MISSING_NPC_ATTACK_RANGE_%s' % npc_id
            skill_id = weapon.get('knightmareFrameSkillId')
            if not skill_id:
                continue
            skill = weapon.get('knightmareFrameSkill')
            if not skill:
                return 'UNKNOWN_NPC_KMF_SKILL_%s' % skill_id
            if not skill.get('attackRange'):
                return 'MISSING_NPC_SKILL_RANGE_%s' % skill_id
            for key in ('knightmareFrameSkillClass', 'activateType'):
                if key not in skill:
                    return 'INCOMPLETE_NPC_KMF_SKILL_%s' % skill_id
            for number in range(1, 7):
                if skill.get('affector%sExcludeAffectorCodeGroupId' % number):
                    return 'UNRETAINED_NPC_EFFECT_GROUP_%s' % skill_id
                affector_id = skill.get('affectorId%s' % number, 0)
                if not affector_id:
                    continue
                affector = skill.get('affector%s' % number)
                if not affector or not affector.get('affectorDetail'):
                    return 'UNKNOWN_NPC_AFFECTOR_%s' % affector_id
                priority = affector.get('priority')
                if affector.get('priorityId') and not priority:
                    return 'UNKNOWN_NPC_SKILL_PRIORITY_%s' % affector['priorityId']
        return None

    def story_catalog_status(self):
        rows = self.all_story_quests()
        story_rows = [row for row in self.story_catalog['quests']
                      if not row.get('onlyStory')]
        tutorial_rows = list(self.tutorial_catalog['quests'])
        by_condition = Counter(
            int(row.get('questFinishConditionId', 0)) for row in rows)
        by_type = Counter(row.get('questType') for row in rows)
        supported = []
        rejected = []
        for row in rows:
            status = self.story_quest_status(int(row['questId']))
            item = {'questId': int(row['questId']), 'name': row.get('name', ''),
                    'chapterId': row.get('chapterId'),
                    'questType': row.get('questType'),
                    'difficulty': row.get('difficulty'), **status}
            (supported if status['supported'] else rejected).append(item)
        return {'pluginVersion': self.story_plugin['version'],
                'pluginEnabled': bool(self.story_plugin['enabled']),
                'dailyBattleCount': len(self.daily_quests()),
                'dailyTypeCount': len(self.daily_type_quests()),
                'dailyDropPolicy': DAILY_MAX_DROP_POLICY,
                'storyBattleCount': len(story_rows),
                'tutorialBattleCount': len(tutorial_rows),
                'additionalBattleCount': (len(rows) - len(story_rows)
                                         - len(tutorial_rows)),
                'battleCountByQuestType': dict(sorted(by_type.items())),
                'battleCount': len(rows), 'supportedCount': len(supported),
                'rejectedCount': len(rejected),
                'battleCountByWinCondition': {
                    str(key): value for key, value in sorted(by_condition.items())},
                'pageCoverage': self.page_coverage(),
                'supportedQuestIds': [row['questId'] for row in supported],
                'rejected': rejected}

    def page_coverage(self):
        external = self.external_catalog['sources']
        return {
            'implemented': [
                'MainStoryTop', 'DailyQuestTop', 'Tutorial',
                'RootEntangleTop', 'EventStoryTop'],
            'missingPageDefinitions': list(external['missingPages']),
            'anotherCharaBattleCount': external['anotherCharaBattleCount'],
            'rootEntangleQuestCount': external['rootEntangleQuestCount'],
            'eventStoryCount': external['eventStoryCount'],
        }

    def _catalog_summary(self, quest_id):
        if not quest_id:
            return None
        row = self.catalog_quest(int(quest_id))
        if row is None:
            return {'questId': int(quest_id), 'found': False}
        is_battle = not row.get('onlyStory')
        status = (self.story_quest_status(row['questId'])
                  if is_battle else
                  {'supported': False, 'reason': 'ONLY_STORY'})
        return {'questId': row['questId'], 'found': True,
                'name': row.get('name', ''), 'questType': row.get('questType'),
                'chapterId': row.get('chapterId'),
                'isBattle': is_battle, **status}

    def battle_catalog_detail(self, quest_id):
        row = self.catalog_quest(int(quest_id))
        if row is None:
            return None
        if row.get('questType') == 'DAILY':
            row = self._with_daily_limits(copy.deepcopy(row))
        main_battles = [item for item in self.story_catalog['quests']
                        if not item.get('onlyStory')]
        tutorial_battles = list(self.tutorial_catalog['quests'])
        if row.get('questType') == 'MAIN':
            global_battles = main_battles
        elif row.get('questType') == 'TUTORIAL':
            global_battles = tutorial_battles + main_battles
        else:
            global_battles = [item for item in self.catalog_quests()
                              if not item.get('onlyStory')
                              and item.get('questType') == row.get('questType')]
        if row.get('onlyStory'):
            global_index = None
            chapter_battles, chapter_index = [], None
        else:
            global_index = next(index for index, item in enumerate(global_battles)
                                if item['questId'] == quest_id)
        if row.get('onlyStory'):
            chapter_battles, chapter_index = [], None
        elif row.get('questType') == 'MAIN':
            chapter_battles = [item for item in global_battles
                               if item.get('questType') == 'MAIN'
                               and item.get('chapterId') == row.get('chapterId')]
            chapter_index = next(index for index, item in enumerate(chapter_battles)
                                  if item['questId'] == quest_id)
        else:
            chapter_battles = [item for item in global_battles
                               if item.get('questType') == row.get('questType')]
            chapter_index = next(index for index, item in enumerate(chapter_battles)
                                  if item['questId'] == quest_id)

        def adjacent(rows, index):
            previous = rows[index - 1] if index is not None and index > 0 else None
            following = (rows[index + 1]
                         if index is not None and index + 1 < len(rows) else None)
            return (self._catalog_summary(previous['questId']) if previous else None,
                    self._catalog_summary(following['questId']) if following else None)

        previous_battle, next_battle = adjacent(chapter_battles, chapter_index)
        global_previous, global_next = adjacent(global_battles, global_index)
        required_chain = []
        seen = set()
        required_id = row.get('requiredQuestId')
        while required_id and required_id not in seen:
            seen.add(required_id)
            item = self._catalog_summary(required_id)
            required_chain.append(item)
            required_row = self.catalog_quest(required_id)
            required_id = required_row.get('requiredQuestId') if required_row else None

        chapter = next((item for item in self.story_catalog.get('chapters', [])
                        if item.get('chapterId') == row.get('chapterId')), None)
        daily = None
        if row.get('questType') == 'DAILY':
            fixture = self.get_fixture(quest_id)
            wave_events = [event for wave in
                           fixture['questData']['waveData']
                           for event in wave['waveEventData']]
            daily_type = row.get('dailyType') or {}
            enemy_rows = [self.npcs[npc_id] for npc_id in
                          dict.fromkeys(row.get('uniqueEnemyNpcIdList') or [])
                          if npc_id in self.npcs]
            daily = {
                'dailyType': copy.deepcopy(daily_type),
                'resetTimeZone': 'Asia/Tokyo',
                'resetAt': 'next JST midnight',
                'weekdayCoefficient': copy.deepcopy(
                    daily_type.get('dayOfWeekCoefficientMap') or {}),
                'maxClearCount': daily_type.get('maxClearCount'),
                'maxAdditionalCount': daily_type.get('maxAdditionalCount'),
                'enemyPool': [{
                    'npcId': enemy['npcId'],
                    'name': enemy.get('name', ''),
                    'bossFlag': bool(enemy.get('bossFlag')),
                    'oneOnOneFlag': bool(enemy.get('oneOnOneFlag')),
                } for enemy in enemy_rows],
                'specialEnemyIds': [enemy['npcId'] for enemy in enemy_rows
                                   if enemy.get('bossFlag') or
                                   enemy.get('oneOnOneFlag')],
                'wavePolicy': copy.deepcopy(
                    fixture.get('schedulePolicy') or {}),
                'waveEventCount': len(wave_events),
                'dropSlotsPerEnemy': len(
                    self.daily_reward_bundle(quest_id)),
                'maxClearRewards': self.daily_max_rewards(quest_id),
                'dropPolicy': DAILY_MAX_DROP_POLICY,
            }
        return {'questId': quest_id,
                'quest': {key: copy.deepcopy(row.get(key)) for key in (
                    'name', 'questType', 'chapterId', 'difficulty', 'onlyStory',
                    'enemyNum', 'questFinishConditionId',
                    'questFinishConditionDescription', 'startAdvNo', 'winAdvNo',
                    'postProcessors', 'postTutorialId', 'activeTutorialId')},
                'status': (self.story_quest_status(quest_id)
                           if not row.get('onlyStory') else
                           {'supported': False, 'reason': 'ONLY_STORY'}),
                'chapter': {'metadata': copy.deepcopy(chapter),
                            'battleCount': len(chapter_battles),
                            'battleIndex': chapter_index},
                'previousBattle': previous_battle,
                'nextBattle': next_battle,
                'globalPreviousBattle': global_previous,
                'globalNextBattle': global_next,
                'requiredQuest': self._catalog_summary(row.get('requiredQuestId')),
                'previousOnlyStoryQuest': self._catalog_summary(
                    row.get('previousOnlyStoryQuestId')),
                'candidateQuest': self._catalog_summary(row.get('candidateQuestId')),
                'requiredChain': required_chain,
                'daily': daily}

    def get_fixture(self, quest_id):
        fixture = self.fixtures.get(quest_id)
        if fixture is not None:
            if (fixture.get('quest', {}).get('questType') == 'DAILY'
                    or fixture.get('quest', {}).get('dailyType')):
                self._with_daily_limits(fixture['quest'])
            return fixture
        if quest_id in self._story_fixture_cache:
            return self._story_fixture_cache[quest_id]
        quest = self.story_quest(quest_id)
        if quest is None:
            raise BattleError('No captured or catalogued battle data for quest %s' % quest_id)
        fixture = self._build_story_fixture(quest)
        self._story_fixture_cache[quest_id] = fixture
        return fixture

    def _build_story_fixture(self, quest):
        status = self.story_quest_status(quest['questId'])
        if not status['supported']:
            raise BattleError('Story battle plugin rejected quest %s: %s'
                              % (quest['questId'], status['reason']))
        wave_policy = self.story_plugin['wave']
        normal_policy = wave_policy['normal']
        special_policy = wave_policy['special']
        if (normal_policy.get('baseSelection') != 'roundRobin'
                or special_policy.get('trigger') != 'afterNormalEnemies'
                or special_policy.get('baseSelection') != 'lastBase'
                or special_policy.get('order') != 'catalog'):
            raise BattleError('Unsupported story battle plugin policy')
        enemy_ids = list(dict.fromkeys(quest.get('uniqueEnemyNpcIdList') or []))
        if not enemy_ids:
            raise BattleError('Story battle %s has no enumerated enemy pool' % quest['questId'])
        missing = [npc_id for npc_id in enemy_ids if npc_id not in self.npcs]
        if missing:
            raise BattleError('Story battle references unknown NPCs: %s' % missing)

        def positions(value):
            result = []
            for item in filter(None, (value or '').split(';')):
                x, y = (int(part) for part in item.split(',', 1))
                result.append({'position': {'x': x, 'y': y}})
            return result

        enemies = [self.npcs[npc_id] for npc_id in enemy_ids]
        bosses = [npc['npcId'] for npc in enemies
                  if npc.get('bossFlag') or npc.get('oneOnOneFlag')]
        normal = [npc['npcId'] for npc in enemies
                  if not (npc.get('bossFlag') or npc.get('oneOnOneFlag'))]
        enemy_count = int(quest['enemyNum'])
        if len(bosses) > enemy_count:
            raise BattleError('Story battle has more special enemies than its enemy count')
        normal_count = enemy_count - len(bosses)
        if normal_count and not normal:
            raise BattleError('Story battle has regular enemy slots but no regular enemy NPC')
        sequence = [normal[index % len(normal)] for index in range(normal_count)] + bosses

        enemy_bases = positions(quest.get('enemyBaseLocations'))
        player_bases = positions(quest.get('allyBaseLocations'))
        if not enemy_bases or not player_bases:
            raise BattleError('Story battle is missing base locations')
        regular_base_count = max(1, len(enemy_bases) - 1)
        wave_events = []
        for index, npc_id in enumerate(sequence):
            is_boss = index >= normal_count
            base_index = len(enemy_bases) - 1 if is_boss else index % regular_base_count
            wave_events.append({
                'waveEventType': 'ENEMY_AT_BASE_LOCATION',
                'timeMilliSeconds': (
                    normal_policy['firstSpawnMilliseconds']
                    + index * normal_policy['intervalMilliseconds']),
                'parameters1': str(base_index), 'parameters2': '1',
                'npcId': npc_id,
            })

        range_data = {}
        npc_status = []
        priority_data = {2: {'priorityId': 2, 'higherLogicCode': 'BLOCK_PLACEMENT',
                            'higherLogicDescription': 'ブロック中＞後から配置した順'}}
        skill_data = {}
        affector_data = {}

        def merge_table(table, key, value, label):
            previous = table.get(key)
            if previous is not None and previous != value:
                raise BattleError('Conflicting NPC %s: %s' % (label, key))
            table[key] = value

        def add_range(definition):
            attack_range = copy.deepcopy(definition)
            attack_range['attackRangeJson'] = attack_range.pop('attackRange')
            merge_table(range_data, attack_range['attackRangeId'], attack_range,
                        'attack range')

        def add_skill(definition):
            row = {k: copy.deepcopy(v) for k, v in definition.items()
                   if not isinstance(v, (dict, list))}
            row['knightmareSkillId'] = row.pop('knightmareFrameSkillId')
            row['skillClass'] = row.pop('knightmareFrameSkillClass')
            row['skillActiveType'] = row.pop('activateType')
            row['skillActiveTypeParameters'] = row.pop(
                'activateTypeParameters', '')
            skill_id = row['knightmareSkillId']
            add_range(definition['attackRange'])
            for number in range(1, 7):
                if definition.get('affector%sExcludeAffectorCodeGroupId' % number):
                    raise BattleError(
                        'NPC KMF skill %s uses an unretained effect group' % skill_id)
                affector_id = definition.get('affectorId%s' % number, 0)
                if not affector_id:
                    continue
                definition_row = definition.get('affector%s' % number)
                if not definition_row:
                    raise BattleError('Missing NPC affector %s' % affector_id)
                if int(definition_row.get('affectorId', 0)) != int(affector_id):
                    raise BattleError('NPC affector ID mismatch for skill %s' % skill_id)
                effect = {k: copy.deepcopy(v) for k, v in definition_row.items()
                          if not isinstance(v, (dict, list))
                          and k != 'affectorDetailId'}
                detail = definition_row['affectorDetail']
                effect['affectorCode'] = detail['affectorCode']
                effect['parameterNum'] = detail['parameterNum']
                effect['integerOrDecimal'] = detail.get(
                    'integerOrDecimal', '').split(',')
                effect['unit'] = detail.get('unit', '').split(',')
                merge_table(affector_data, affector_id, effect, 'affector')
                priority = definition_row.get('priority')
                if definition_row.get('priorityId') and priority:
                    priority_row = {'priorityId': priority['priorityId'],
                                    'higherLogicCode': priority['code'],
                                    'higherLogicDescription': priority.get(
                                        'description', '')}
                    merge_table(priority_data, priority['priorityId'],
                                priority_row, 'priority')
            merge_table(skill_data, skill_id, row, 'KMF skill')
        for npc_id in enemy_ids:
            npc = self.npcs[npc_id]
            weapon = self.weapons.get(npc.get('knightmareFrameCustomizeId'))
            if weapon is None:
                raise BattleError('NPC %s has no retained weapon definition' % npc_id)
            frame = self.kmfs.get(weapon['knightmareFrameId'], {})
            add_range(weapon['attackRange'])
            skill_id = int(weapon.get('knightmareFrameSkillId', 0) or 0)
            if skill_id:
                add_skill(weapon['knightmareFrameSkill'])
            method = weapon['attackMethodType']
            npc_status.append({
                'npcId': npc_id,
                'nickname': npc.get('name', ''),
                'enShortName': npc.get('enShortName', ''),
                'description': npc.get('description', ''),
                'charaName': npc.get('fullName', ''),
                'knightmareId': weapon['knightmareFrameCustomizeId'],
                'knightmareName': frame.get('name', npc.get('fullName', '')),
                'weaponName': weapon.get('name', ''),
                'heroFlag': False,
                'priorityId': 2,
                'attribute': 'KNIGHT',
                'targetNum': weapon.get('attackType', '1'),
                'targetNumDescription': weapon.get('attackTypeDescription', ''),
                'attackPriorityDescription': weapon.get(
                    'additionalAttackPriorityDescription', ''),
                'moveType': npc.get('moveType', weapon.get('moveType', 'GROUND')),
                'attackMethodType': method,
                'attackRangeId': weapon['attackRangeId'],
                'hp': int(npc.get('hp', 1)),
                'attackPoint': int(npc.get('attack', 0)),
                'attackAccuracy': int(npc.get('hitAccuracy', 1000)),
                'attackIntervalMilliSeconds': 1170,
                'defensePoint': int(npc.get('defense', 0)),
                'avoidance': int(npc.get('avoidRate', 1000)),
                'moveSpeedMilliSeconds': int(weapon.get('moveSpeed', 3500)),
                'moveSpeedMilliSecondsWhenTurn': int(weapon.get('curveMoveSpeed', 2800)),
                'affiliation': [],
                'kmfAffiliation': [int(v) for v in frame.get('affiliationIds', '').split(',') if v],
                'enemyType': npc.get('enemyType', 'NORMAL'),
                'aiType': ('OFFENSE_UNIT_FAR_TYPE_AI' if method == 'FAR' else
                           'OFFENSE_UNIT_NEAR_TYPE_AI'),
                'isBoss': bool(npc.get('bossFlag')),
                'isOneOnOne': bool(npc.get('oneOnOneFlag')),
                'isPilotUnknown': False,
                'knightmareSkillId': skill_id,
                'knightmareSkillLevel': 1 if skill_id else 0,
                'canAutoInvokeKnightmareFrameSkill': bool(skill_id),
            })

        field = copy.deepcopy(quest.get('field') or {})
        mission = {}
        gimmick_data = {}
        gimmick_ranges = {}
        placed_gimmicks = []
        for number in (1, 2, 3):
            gimmick_id = quest.get('gimmickId%s' % number)
            if not gimmick_id:
                continue
            definition = self.gimmicks.get(gimmick_id)
            if definition is None:
                raise BattleError(
                    'Missing gimmick definition %s' % gimmick_id)
            row = {k: copy.deepcopy(v) for k, v in definition.items()
                   if not isinstance(v, (dict, list))}
            row['rangeId'] = row.pop('attackRangeId')
            row['gimmickName'] = row['name']
            row['unlockKnightmareIds'] = definition.get(
                'unlockKnightmareIds', [])
            merge_table(gimmick_data, gimmick_id, row, 'gimmick')
            attack_range = copy.deepcopy(definition['attackRange'])
            attack_range['attackRangeJson'] = attack_range.pop('attackRange')
            merge_table(gimmick_ranges, attack_range['attackRangeId'],
                        attack_range, 'gimmick attack range')
            for index, location in enumerate(positions(
                    quest.get('gimmickLocations%s' % number)), start=1):
                placed_gimmicks.append({
                    'gimmickUniqueId': '%s-%s-%s' % (
                        quest['questId'], number, index),
                    'gimmickId': gimmick_id,
                    'location': location['position'],
                })
        for number in (1, 2, 3):
            definition = quest.get('questMission%s' % number) or {}
            mission['missionId%s' % number] = quest.get('questMissionId%s' % number)
            mission['missionCode%s' % number] = definition.get('questMissionCode', '')
            mission['missionParameters%s' % number] = quest.get('questMissionParameters%s' % number, '')
            mission['missionDescription%s' % number] = quest.get('questMissionDescription%s' % number, '')

        quest_data = {
            'questId': quest['questId'], 'chapterNo': str(quest.get('chapterId', '')),
            'chapterTitle': '', 'questName': quest['name'] or '',
            'questType': quest['questType'], 'questDifficulty': quest.get('difficulty', 'NORMAL'),
            'dailyType': '', 'areaName': field.get('name', ''),
            'recommendedStrength': quest.get('recommendedStrength', ''),
            'enemyNum': enemy_count,
            'fieldData': {'fieldId': field.get('fieldId', quest.get('fieldId')),
                          'fieldType': field.get('fieldTypeNo', 10),
                          'name': field.get('name', ''), 'enName': field.get('enName', ''),
                          'description': field.get('description', '')},
            'mapDataNo': quest['mapDataNo'], 'initialSortieCost': quest['initialGlobalCost'],
            'placeUnitMaxCount': quest['maxPlacementUnitNum'],
            'bgmFileName': quest.get('bgm', ''), 'bossBgmFileName': quest.get('bossBgm', ''),
            'returnStaminaOnFail': 0,
            'winLoseConditionData': {'condition': status['winConditionCode'],
                'parameters': str(quest.get('questFinishConditionParameters', 0)),
                'description': quest.get('questFinishConditionDescription', '')},
            'missionData': mission, 'playerBaseCampData': player_bases,
            'enemyBaseCampData': enemy_bases,
            'waveData': [{'timeMilliSeconds': 0, 'waveEventData': wave_events}],
            'npcStatusData': npc_status, 'npcAttackRangeData': list(range_data.values()),
            'npcPriorityData': list(priority_data.values()),
            'npcSkillData': [], 'npcKnightmareSkillData': list(skill_data.values()),
            'npcAffectorData': list(affector_data.values()),
            'npcAffectorCodeGroupData': [], 'placedGimmickData': placed_gimmicks,
            'userGimmickData': [], 'gimmickData': list(gimmick_data.values()),
            'gimmickRangeData': list(gimmick_ranges.values()),
            'advData': copy.deepcopy(quest.get('advData') or {}),
            'enabledNavi': bool(quest.get('enabledNavi')),
            'playerInvalidateAffectorCodes': (
                str(quest.get('playerInvalidateAffectorCodes') or '').split(',')
                if quest.get('playerInvalidateAffectorCodes') else []),
            'playerInvalidateGimmickCodes': (
                str(quest.get('playerInvalidateGimmickCodes') or '').split(',')
                if quest.get('playerInvalidateGimmickCodes') else []),
            'limitTransformKnightmareIds': [
                int(value) for value in str(
                    quest.get('limitTransformKnightmareFrameIds') or '').split(',')
                if value],
            'higherStrategicCommandData': copy.deepcopy(
                quest.get('higherStrategicCommandData') or []),
            'questBoundSkillData': copy.deepcopy(
                quest.get('questBoundSkillData') or []),
            'conditionRate': quest.get('conditionRate', ''),
            'conditionTotalLevel': int(quest.get('conditionTotalLevel') or 0),
            'introTeamEntryUnitIndex1': '', 'introTeamEntryUnitIndex2': '',
            'resultUnitIndex': '',
        }
        fixture = {
            'sources': {
                'catalog': 'main_story_catalog.json',
                'npcMaster': 'DailyQuestTop.static.json',
                'guides': [
                    'https://appmedia.jp/geass_ls/75587593',
                    'https://appmedia.jp/geass_ls/75974279',
                    'https://smartgame-post.com/geass_loststories-beginner/',
                    'https://benikikyonomori.com/code-geass-lost-stories-ch2-p22/',
                ],
            },
            'schedulePolicy': {
                'kind': 'CATALOG_GUIDE_FALLBACK',
                'pluginVersion': self.story_plugin['version'],
                'normalIntervalMilliseconds': normal_policy['intervalMilliseconds'],
                'firstSpawnMilliseconds': normal_policy['firstSpawnMilliseconds'],
                'specialTrigger': special_policy['trigger'],
                'specialEnemyBase': special_policy['baseSelection'],
                'note': 'Enemy IDs, counts, boss flags and bases are client data; exact wave timing is not retained for this stage.'
            },
            'quest': copy.deepcopy(quest),
            'questData': quest_data,
            'dropRewards': {},
            'affiliationData': copy.deepcopy(self.fixtures[519001]['affiliationData']),
            'affectorCodeGroupData': copy.deepcopy(self.fixtures[519001]['affectorCodeGroupData']),
        }
        return fixture

    def assemble(self, pairs, progress, player_sex='MALE', quest_id=512001):
        fixture = self.get_fixture(quest_id)
        catalog_constraints = fixture['quest'].get('catalogConstraints') or {}
        max_card_stats = (catalog_constraints.get('questBattleConditionCode')
                         == 'CARD_LEVEL_REVISION_MAX')
        tables = {key: {} for key in ('attackRangeData', 'priorityData', 'pilotSkillData',
                  'knightmareSkillData', 'affectorData', 'knightmareFeatureSkillData',
                  'pilotFeatureSkillData', 'transformDetailData', 'affectorCodeGroupData')}
        groups = {}
        required_gimmicks = set()

        def index_groups(node):
            if isinstance(node, dict):
                if 'affectorCodeGroupId' in node and isinstance(node.get('affectorCodes'), list):
                    groups[node['affectorCodeGroupId']] = copy.deepcopy(node)
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        index_groups(value)
            elif isinstance(node, list):
                for value in node:
                    index_groups(value)
        if hasattr(self, '_groups'):
            groups = self._groups
        else:
            index_groups(self.master)
            index_groups(self.daily_master)
            # Captured global code groups are static definitions, not player state.
            for captured in self.fixtures.values():
                for node in captured.get('affectorCodeGroupData', []):
                    groups.setdefault(node['affectorCodeGroupId'], node)
            self._groups = groups

        def walk(node):
            if isinstance(node, list):
                for child in node:
                    walk(child)
            elif isinstance(node, dict):
                for key, value in node.items():
                    if key.endswith('AffectorCodeGroupId') and value:
                        if value not in groups:
                            raise BattleError('Missing status effect group %s' % value)
                        tables['affectorCodeGroupData'][value] = groups[value]
                    if re.fullmatch(r'affector\d+GimmickId\d+', key) and value:
                        required_gimmicks.add(value)
                if 'attackRangeId' in node and isinstance(node.get('attackRange'), str):
                    row = {k:v for k,v in node.items() if not isinstance(v,(dict,list))}
                    row['attackRangeJson'] = row.pop('attackRange')
                    tables['attackRangeData'][row['attackRangeId']] = row
                if 'priorityId' in node and 'code' in node:
                    tables['priorityData'][node['priorityId']] = {
                        'priorityId': node['priorityId'], 'higherLogicCode': node['code'],
                        'higherLogicDescription': node.get('description', '')}
                if 'affectorId' in node and 'affectorDetail' in node:
                    row = {k:v for k,v in node.items() if not isinstance(v,(dict,list))
                           and k != 'affectorDetailId'}
                    detail = node['affectorDetail']
                    for key in ('affectorCode', 'parameterNum'):
                        row[key] = detail[key]
                    for key in ('integerOrDecimal', 'unit'):
                        row[key] = detail.get(key, '').split(',')
                    tables['affectorData'][row['affectorId']] = row
                for old, new, table, cls in (
                    ('cardSkillId','pilotSkillId','pilotSkillData','cardSkillClass'),
                    ('knightmareFrameSkillId','knightmareSkillId','knightmareSkillData','knightmareFrameSkillClass')):
                    if old in node and 'activateType' in node:
                        row = {k:v for k,v in node.items() if not isinstance(v,(dict,list))}
                        row[new] = row.pop(old)
                        row['skillClass'] = row.pop(cls)
                        row['skillActiveType'] = row.pop('activateType')
                        if 'activateTypeParameters' in row:
                            row['skillActiveTypeParameters'] = row.pop('activateTypeParameters')
                        tables[table][row[new]] = row
                if 'kmfFeatureSkillId' in node and 'activateType' in node:
                    row = {k:v for k,v in node.items() if not isinstance(v, (dict, list))}
                    tables['knightmareFeatureSkillData'][row['kmfFeatureSkillId']] = row
                if 'cardFeatureSkillId' in node and 'activateType' in node:
                    row = {k:v for k,v in node.items() if not isinstance(v, (dict, list))}
                    row['pilotFeatureSkillId'] = row.pop('cardFeatureSkillId')
                    row['pilotFeatureSkillClass'] = row.pop('cardSkillClass')
                    tables['pilotFeatureSkillData'][row['pilotFeatureSkillId']] = row
                for child in node.values():
                    if isinstance(child,(dict,list)):
                        walk(child)

        pilots, kmfs = [], []
        for pilot, kmf in pairs:
            card = self.cards[pilot.mst_pilot_id]
            battle_pilot = pilot
            if not card.get('rarity', {}).get('maxCardLevelList'):
                raise BattleError('This retained card is a non-player or incomplete definition')
            if max_card_stats:
                battle_pilot = copy.copy(pilot)
                battle_pilot.level = card['rarity']['maxCardLevelList'][pilot.limit_break]
                battle_pilot.awakening_level = int(
                    card['rarity'].get('maxRevision', pilot.awakening_level))
            character = self.characters[card['charaId']]
            weapon = self.weapons[kmf.customization_id]
            frame = self.kmfs[kmf.mst_kmf_id]
            if frame.get('mobFlag'):
                raise BattleError('This retained KMF is an enemy-only definition')
            if weapon['knightmareFrameId'] != kmf.mst_kmf_id:
                raise BattleError('KMF weapon does not belong to this frame')
            features = {r['cardFeatureId']: r for r in card.get('cardFeatureList', [])}
            if any(fid not in features for fid in pilot.unlocked_feature_ids):
                raise BattleError('Unknown unlocked pilot feature')
            # Do not include locked feature dependencies or unrelated weapon
            # change forms in the native skill tables.
            walk({k:v for k,v in card.items() if k != 'cardFeatureList'})
            for fid in pilot.unlocked_feature_ids:
                walk(features[fid])
            walk(weapon)
            stats = pilot_stats(card, battle_pilot.level,
                              battle_pilot.awakening_level)
            row = {'userPilotId':pilot.user_card_id, 'userKnightmareId':kmf.user_kmf_id,
                   'pilotId':card['cardId'], 'charaId':card['charaId'],
                   'level':battle_pilot.level,
                   'maxLevel':card['rarity']['maxCardLevelList'][pilot.limit_break],
                   'awakeRankFrameNo':min(6, battle_pilot.awakening_level // 3 + 1),
                   'heroFlag':card.get('heroFlag',False),
                   'charaName':character['fullName'], 'nickname':card['name'],
                   'enShortName':character['enShortName'],
                   'sex':player_sex if card.get('heroFlag') else character['sex'],
                   'rarity':card['rarity']['rarityNum'], 'priorityId':card['priorityId'],
                   'attribute':card['attribute'],
                   'pilotFeatureSkillIds':[features[fid]['cardFeatureSkillId'] for fid in pilot.unlocked_feature_ids],
                   'affiliation':[int(v) for v in card.get('affiliationIds','').split(',') if v],
                   'getInDedicatedKnightmareFrame':kmf.mst_kmf_id in card.get('combinationKnightmareFrameIdList',[])}
            mapping = {'cost':'sortieCost','blockNum':'maxBlockingCount','avoidRate':'avoidance',
                       'nearHitAccuracy':'nearAttackAccuracy','farHitAccuracy':'farAttackAccuracy',
                       'nearAttackInterval':'nearAttackIntervalMilliSeconds',
                       'farAttackInterval':'farAttackIntervalMilliSeconds'}
            for key in ('hp','cost','blockNum','avoidRate','nearAttackAdjust','farAttackAdjust',
                        'defenseAdjust','nearHitAccuracy','farHitAccuracy','nearAttackInterval',
                        'farAttackInterval','relocationTime'):
                row[mapping.get(key,key)] = stats[key]
            skills = pilot_skills(card, battle_pilot)
            for number in range(1, 7):
                if card.get('cardSkillId%s' % number):
                    row['pilotSkillId%s'%number] = card['cardSkillId%s'%number]
                    row['pilotSkillLevel%s'%number] = skills['cardSkillLevel%s' % number]
                    if number > 2:
                        # Retained definitions repeat the parent skill's exact
                        # title for extra effect slots. Require a unique match;
                        # slot number alone is wrong for cards such as 103048.
                        child = card['cardSkill%s' % number]
                        parents = [i for i in (1, 2) if card.get('cardSkill%s' % i, {}).get('name') == child['name']]
                        if len(parents) != 1:
                            raise BattleError('Ambiguous pilot skill parent')
                        row['pilotSkillParentIndex%s'%number] = parents[0]
                    unlock = card.get('unlockCardSkillLevel%s'%number, 0)
                    row['pilotSkillLocked%s'%number] = skills['cardSkillLocked%s' % number]
                    row['pilotSkillUnlockLevel%s'%number] = unlock
            for key in ('invalidateAffectorCodeGroupId', 'activateByManualSkillNumbers',
                        'activateSkillCost', 'activateSkillCoolTime',
                        'deactivateSkillCost', 'deactivateSkillCoolTime'):
                if key in card:
                    row[key] = copy.deepcopy(card[key])
            pilots.append(row)
            ks = kmf_stats(weapon, kmf.revision)
            kmf_row = {'userKnightmareId':kmf.user_kmf_id,'awakeRankFrameNo':kmf.revision_class,
                'knightmareId':weapon['knightmareFrameCustomizeId'], 'knightmareName':frame['name'],
                'weaponName':weapon['name'],'targetNum':weapon['attackType'],
                'targetNumDescription':weapon['attackTypeDescription'], 'moveType':weapon['moveType'],
                'attackMethodType':weapon['attackMethodType'],'sortieCost':ks['cost'],
                'maxBlockingCount':ks['blockNum'],'attackRangeId':weapon['attackRangeId'],
                'attackPoint':ks['attack'],'defensePoint':ks['defense'],
                'moveSpeedMilliSeconds':weapon['moveSpeed'],
                'moveSpeedMilliSecondsWhenTurn':weapon['curveMoveSpeed'],
                # Early unarmed/basic KMFs legitimately have no active skill.
                'knightmareSkillId':weapon.get('knightmareFrameSkillId', 0),
                'knightmareSkillLevel':ks['skillLevel'],
                'affiliation':[int(v) for v in frame.get('affiliationIds','').split(',') if v],
                'isDefaultColor':True}
            color = custom_color_state(
                getattr(kmf, 'upgrade_ranks', None))
            if color is not None and color['enabled']:
                kmf_row.update({
                    'isDefaultColor': False,
                    'customColorR': color['r'],
                    'customColorG': color['g'],
                    'customColorB': color['b'],
                })
            for key in ('invalidateAffectorCodeGroupId', 'vertical', 'beside',
                        'initialSortieWaitMilliSeconds', 'transformKnightmareId',
                        'transformKnightmareSkillId'):
                if key in weapon:
                    kmf_row[key] = weapon[key]
            if 'additionalAttackPriorityDescription' in weapon:
                kmf_row['attackPriorityDescription'] = weapon['additionalAttackPriorityDescription']
            for number in range(1, 6):
                key = 'kmfFeatureSkillId%s' % number
                if weapon.get(key):
                    if weapon[key] not in tables['knightmareFeatureSkillData']:
                        raise BattleError('Missing KMF feature skill')
                    kmf_row[key] = weapon[key]
            def add_transform(transform, skill_id):
                if not skill_id or skill_id not in tables['knightmareSkillData']:
                    raise BattleError('Missing transformed KMF skill')
                detail = {'id': transform['transformKnightmareFrameId'],
                    'knightmareId': transform['knightmareFrameCustomizeId'],
                    'knightmareName': transform['knightmareFrameName'],
                    'targetNum': transform['attackType'], 'attackRangeId': transform['attackRangeId'],
                    'knightmareSkillId': skill_id, 'moveType': transform['moveType']}
                # The retained 1030/1035 DTOs omit attackMethodType as well.
                # Absence lets the native client keep its current method.
                for key in ('attackMethodType', 'invalidateAffectorCodeGroupId', 'vertical', 'beside'):
                    if key in transform:
                        detail[key] = transform[key]
                for number in range(1, 6):
                    key = 'kmfFeatureSkillId%s' % number
                    if transform.get(key):
                        detail[key] = transform[key]
                # Native TransformDetailData uses detail IDs, not frame or
                # owned-instance IDs, for weapon changes after a union.
                for number in range(1, 4):
                    key = 'weaponChangeTransformKnightmareFrameId%s' % number
                    if transform.get(key):
                        detail['weaponChangeTransformDetailId%s' % number] = transform[key]
                if transform.get('extendTransformKnightmareFrameId'):
                    detail['extendTransformDetailId'] = transform['extendTransformKnightmareFrameId']
                previous = tables['transformDetailData'].get(detail['id'])
                if previous is not None and previous != detail:
                    raise BattleError('Conflicting transformed KMF definition')
                tables['transformDetailData'][detail['id']] = detail
                return detail

            for suffix in ('', '2', '3'):
                transform = weapon.get('transformKnightmareFrame' + suffix)
                if not transform:
                    continue
                detail = add_transform(transform, weapon.get('transformKnightmareSkillId' + suffix))
                kmf_row['transformDetailId' + suffix] = detail['id']
            allowed = weapon.get('allowTransformKnightmareFrameList', [])
            if set(weapon.get('allowTransformKnightmareFrameIdList', [])) != {
                    t['transformKnightmareFrameId'] for t in allowed}:
                raise BattleError('Incomplete allowed union forms')
            # The retained family declares one transform skill shared by its
            # allowed forms. Features/range/method remain specific to each form.
            for transform in allowed:
                add_transform(transform, weapon.get('transformKnightmareSkillId'))
            kmfs.append(kmf_row)
        player = {k:list(v.values()) for k,v in tables.items()}
        player.update({'isCleared':bool(progress.get('clearedAt')),
            'clearRank':progress.get('bestQuestRank','NONE'), 'sex':player_sex,
            'playerMissionData':{'isAchievedMission%s'%i:progress.get('clearedMission%s'%i,False) for i in (1,2,3)},
            'playerAttributeRankData':{k+'RankLv':0 for k in ('knight','rook','bishop','queen','king','star')},
            'pilotStatusData':pilots,'knightmareStatusData':kmfs,
            'expeditionData':{'pilotStatusData':[], 'knightmareStatusData':[]},
            'multiFrontData':{'extraGimmickData':[], 'extraGimmickRangeData':[], 'extraUserGimmickData':[]},
            'closeFunction':[], 'usedPlayerSkill':False, 'hasSubscription':False,
            'retryWeakenedData':{'retryItemTotalNum':0,'retryItemConsumptionNum':1,
                'moneyTotalNum':0,'presentMoneyTotalNum':0,'consumptionNum':50}})
        quest = copy.deepcopy(fixture['questData'])
        gimmicks = {r['gimmickId']:r for r in quest['gimmickData']}
        ranges = {r['attackRangeId']:r for r in quest['gimmickRangeData']}
        for gid in required_gimmicks:
            definition = self.gimmicks.get(gid)
            if definition is None:
                raise BattleError('Missing skill gimmick %s' % gid)
            row = {k:v for k,v in definition.items() if not isinstance(v, (dict,list))}
            row['rangeId'] = row.pop('attackRangeId')
            row['gimmickName'] = row['name']
            # Empty unlockKnightmareIds is the observed DTO default.
            row['unlockKnightmareIds'] = definition.get('unlockKnightmareIds', [])
            gimmicks[gid] = row
            attack_range = copy.deepcopy(definition['attackRange'])
            attack_range['attackRangeJson'] = attack_range.pop('attackRange')
            ranges[attack_range['attackRangeId']] = attack_range
        quest['gimmickData'], quest['gimmickRangeData'] = list(gimmicks.values()), list(ranges.values())
        affiliations = {r['affiliationId']:copy.deepcopy(r) for r in fixture['affiliationData']}
        for definition in self.master['affiliationList']:
            if definition.get('side'):
                affiliations[definition['affiliationId']] = {
                    'affiliationId':definition['affiliationId'], 'affiliationGroupId':definition['side']}
        battle = {'questData':quest, 'playerData':player,
                  'affiliationData':list(affiliations.values())}
        from .battle_validation import validate_battle
        validate_battle(battle)
        return battle
