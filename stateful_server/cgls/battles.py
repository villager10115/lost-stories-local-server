"""Atomic local battle lifecycle for catalogued daily and story quests."""
from collections import Counter
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
import re

from sqlalchemy import select, text

from .battle_data import BattleData, BattleError, pilot_stats, pilot_skills
from .models import LocalBattle, LocalBattleProgress, UserPilot, UserKmf, UserWallet, UserGameItem
from .progression import _validate_request_id, _add_experience, _add_bonds, EXP_TABLE, _pilot_response

JST = timezone(timedelta(hours=9))


def skip_ticket_count(session, user_id, wallet):
    # Starter allocations use the wallet; mission/present grants use items.
    # Both are real existing balances. Read/debit both without rewriting saves.
    item = session.get(UserGameItem,(user_id,'SKIP_QUEST'))
    return (wallet.skip_tickets if wallet else 0) + (item.quantity if item else 0)


class BattleService:
    CAPTURED_DAILY_QUESTS = (512001, 519001)
    def __init__(self, sessions, user_id, masterdata, clock=None):
        self.sessions, self.user_id = sessions, user_id
        self.data = BattleData(masterdata)
        self.SUPPORTED_QUESTS = tuple(
            int(row['questId']) for row in self.data.daily_quests())
        self.clock = clock or (lambda:datetime.now(JST))

    def fixture(self, quest_id):
        return self.data.get_fixture(quest_id)

    def initial_progress(self, quest_id=512001):
        quest = (self.data.daily_quest(quest_id) or
                 self.data.catalog_quest(quest_id) or
                 self.fixture(quest_id)['quest'])
        return {'questId':quest_id,'quest':copy.deepcopy(quest),
                'questStatus':'OPENED','bestQuestRank':'NONE','isNew':False,
                'clearedMission1':False,'clearedMission2':False,'clearedMission3':False,
                'createdAt':self.clock().isoformat()}

    def progress(self, session, quest_id=512001):
        row = session.get(LocalBattleProgress,(self.user_id,quest_id))
        return copy.deepcopy(row.state) if row else self.initial_progress(quest_id)

    def player_state(self, session):
        row = session.get(LocalBattleProgress, (self.user_id, 0))
        return copy.deepcopy(row.state) if row else {}

    def update_player_state(self, session, **values):
        state = self.player_state(session)
        state.update(values)
        row = session.get(LocalBattleProgress, (self.user_id, 0))
        if row is None:
            row = LocalBattleProgress(
                user_id=self.user_id, quest_id=0, state=state)
            session.add(row)
        else:
            row.state = state
        return state

    def battle_card_data(self, pilot):
        card = self.data.cards[pilot.mst_pilot_id]
        return {**_pilot_response(pilot),
                **pilot_stats(card, pilot.level, pilot.awakening_level),
                **pilot_skills(card, pilot),
                'revisionClass': min(6, pilot.awakening_level // 3 + 1),
                'unlockedFeatureIdList': pilot.unlocked_feature_ids}

    def game_user_progress(self, session):
        experience = int(self.player_state(session).get('experience', 0))
        levels = sorted(self.data.master.get('levelList', []), key=lambda row: row['id'])
        current = next((row for row in reversed(levels)
                        if int(row.get('experience', 0)) <= experience),
                       {'id': 1, 'experience': 0})
        rank = int(current['id'])
        following = next((row for row in levels if int(row['id']) == rank + 1), None)
        return {'userId': self.user_id, 'experience': experience, 'rank': rank,
                'totalExpForCurrentLevel': int(current.get('experience', 0)),
                'totalExpForNextLevel': int(
                    following.get('experience', experience) if following else experience)}

    def user_statuses(self, wallet, now):
        stamp = now if isinstance(now, str) else now.isoformat()
        stamina = wallet.stamina if wallet else 0
        max_stamina = wallet.max_stamina if wallet else 0
        return [
            {'statusId': status_id, 'point': point,
             'checkPeriod': period, 'periodicPoint': periodic,
             'checkedAt': stamp, 'createdAt': stamp}
            for status_id, point, period, periodic in (
                ('ACP', stamina, 6, 1),
                ('MAX_ACP', max_stamina, 0, 0),
                ('UEP', 10, 1, 0),
                ('MAX_UEP', 10, 0, 0),
                ('MAX_DECK', 10, 0, 0),
                ('MAX_FRIEND', 15, 0, 0),
                ('BTP', 5, 1, 0),
                ('MAX_BTP', 5, 0, 0),
            )
        ]

    def apply_quest_post_processors(self, session, quest_id):
        quest = self.fixture(quest_id)['quest']
        processors = {
            value.strip() for value in
            str(quest.get('postProcessors') or '').split(',')
            if value.strip()}
        if 'TUTORIAL_ID_SET' in processors:
            tutorial_id = str(quest.get('postTutorialId') or '')
            if not tutorial_id:
                raise BattleError('Tutorial completion has no next tutorial ID')
            self.update_player_state(session, tutorialId=tutorial_id)

    def daily(self, session, quest_id=512001, period=None, records=None):
        quest = self.data.daily_quest(quest_id)
        if quest is None:
            raise BattleError('Quest %s is not a daily battle' % quest_id)
        daily_type = quest['dailyType']
        period = period or self.clock().date().isoformat()
        reset_value = self.player_state(session).get('dailyCountResetAt')
        reset_time = None
        if reset_value:
            try:
                reset_time = datetime.fromisoformat(reset_value)
            except (TypeError, ValueError):
                reset_time = None
        if records is None:
            records = session.scalars(select(LocalBattle).where(
                LocalBattle.user_id==self.user_id, LocalBattle.period==period,
                LocalBattle.status.in_(('DONE','SKIPPED')))).all()
        count = 0
        for record in records:
            if reset_time is not None:
                completed = (record.finish_response or {}).get('currentTime')
                try:
                    if completed and datetime.fromisoformat(completed) < reset_time:
                        continue
                except (TypeError, ValueError):
                    pass
            started = record.start_response.get('battle', {}).get(
                'questData', {})
            daily = started.get('dailyType', {})
            name = (daily.get('name') if isinstance(daily, dict) else daily)
            if not name:
                daily_quest = self.data.daily_quest(record.quest_id)
                name = ((daily_quest or {}).get('dailyType') or {}).get('name')
            if name != daily_type['name']:
                continue
            if (record.status == 'SKIPPED' or
                    record.finish_response['battleResult']['result'] == 'WIN'):
                count += 1
        now = self.clock().isoformat()
        return {'dailyType':copy.deepcopy(daily_type),
                'dailyTypeName':daily_type['name'],'dailyClearCount':count,
                'dailyAdditionalCount':0,'recentClearedAt':now,'recentAdditionalAt':now,'createdAt':now}

    def daily_all(self, session):
        period = self.clock().date().isoformat()
        records = session.scalars(select(LocalBattle).where(
            LocalBattle.user_id==self.user_id, LocalBattle.period==period,
            LocalBattle.status.in_(('DONE','SKIPPED')))).all()
        return [
            self.daily(session, int(quest['questId']), period, records)
            for quest in self.data.daily_type_quests().values()
        ]

    def validate_payload(self, payload):
        quest_id = payload['questId']
        if quest_id not in self.SUPPORTED_QUESTS:
            status = self.data.story_quest_status(quest_id)
            if not status['supported']:
                raise BattleError('このクエストは自動設定できません: %s'
                                  % status['reason'])
        if (payload.get('usedDailyQuestDropBoostItem')
                and self.data.daily_quest(quest_id) is None):
            raise BattleError('ドロップブーストはデイリークエスト専用です。')
        if not re.fullmatch(r'MAIN(?:[1-9]|1[0-5])', payload.get('deckType', '')):
            raise BattleError('Unsupported battle deck type')
        cards, kmfs = payload['userCardIdList'], payload['userKnightmareFrameIdList']
        if not 1 <= len(cards) <= 10 or len(cards)!=len(kmfs) or len(set(cards))!=len(cards) or len(set(kmfs))!=len(kmfs):
            raise BattleError('Choose 1–10 distinct owned pilot/KMF pairs')
        return quest_id

    def validate_catalog_deck(self, quest_id, pairs):
        quest = self.data.story_quest(quest_id) or {}
        constraints = quest.get('catalogConstraints') or {}
        if not constraints:
            return
        allowed_cards = {
            int(value) for value in
            str(constraints.get('battleParameters') or '').split(',')
            if value.strip().isdigit()}
        pilot_affiliations = {
            int(value) for value in
            str(constraints.get('parameters') or '').split(',')
            if value.strip().isdigit()}
        kmf_affiliations = {
            int(value) for value in
            str(constraints.get('parameters2') or '').split(',')
            if value.strip().isdigit()}
        conditions = (
            (constraints.get('questDeckConditionCode'), pilot_affiliations),
            (constraints.get('questDeckConditionCode2'), kmf_affiliations),
        )
        for pilot, kmf in pairs:
            card = self.data.cards[pilot.mst_pilot_id]
            weapon = self.data.weapons[kmf.customization_id]
            frame = self.data.kmfs[weapon['knightmareFrameId']]
            if allowed_cards and card['cardId'] not in allowed_cards:
                raise BattleError('このクエストでは指定されたカードのみ編成できます')
            for code, allowed_affiliations in conditions:
                if not code or not allowed_affiliations:
                    continue
                owner = card if code == 'DESIGNATION_AFFILIATION' else frame
                if code not in (
                        'DESIGNATION_AFFILIATION',
                        'DESIGNATION_AFFILIATION_KMF'):
                    raise BattleError('未対応の編成条件です: %s' % code)
                affiliations = {int(value) for value in
                                str(owner.get('affiliationIds') or '').split(',')
                                if value.strip().isdigit()}
                if not affiliations & allowed_affiliations:
                    raise BattleError('編成ユニットの所属がクエスト条件を満たしていません')

    def owned_pairs(self, session, payload):
        cards, kmfs = payload['userCardIdList'], payload['userKnightmareFrameIdList']
        owned_pilots = {r.user_card_id:r for r in session.scalars(select(UserPilot).where(UserPilot.user_id==self.user_id))}
        owned_kmfs = {r.user_kmf_id:r for r in session.scalars(select(UserKmf).where(UserKmf.user_id==self.user_id))}
        if any(c not in owned_pilots for c in cards) or any(k not in owned_kmfs or owned_kmfs[k].is_in_storage for k in kmfs):
            raise BattleError('Formation contains unavailable or unowned units')
        pairs = [(owned_pilots[c],owned_kmfs[k]) for c,k in zip(cards,kmfs)]
        for pilot, kmf in pairs:
            card = self.data.cards.get(pilot.mst_pilot_id, {})
            weapon = self.data.weapons.get(kmf.customization_id, {})
            frame = self.data.kmfs.get(kmf.mst_kmf_id, {})
            if (not card.get('rarity', {}).get('maxCardLevelList') or
                    weapon.get('knightmareFrameId') != kmf.mst_kmf_id or not frame or frame.get('mobFlag')):
                raise BattleError('Formation contains an invalid player unit definition')
        self.validate_catalog_deck(payload['questId'], pairs)
        return pairs

    def drop_coefficient(self, now, quest_id=512001):
        weekdays = ['MONDAY','TUESDAY','WEDNESDAY','THURSDAY','FRIDAY','SATURDAY','SUNDAY']
        quest = (self.data.daily_quest(quest_id) or
                 self.data.catalog_quest(quest_id) or {})
        daily_type = quest.get('dailyType')
        if not daily_type:
            return 1.0
        return float(daily_type['dayOfWeekCoefficientMap'].get(weekdays[now.weekday()],1))

    def grant_experience(self, session, pairs, quest_id=512001):
        changed = []
        q = self.fixture(quest_id)['quest']
        for pilot, kmf in pairs:
            card = self.data.cards[pilot.mst_pilot_id]
            pilot.level,pilot.experience = _add_experience(pilot.level,pilot.experience,
                q['cardExp'],card['rarity']['maxCardLevelList'][pilot.limit_break],EXP_TABLE[card['rarity']['rarity']])
            pilot.bonds_level,pilot.bonds_point = _add_bonds(pilot.bonds_level,pilot.bonds_point,q['bondsExp'])
            changed.append(self.battle_card_data(pilot))
        player = session.get(LocalBattleProgress,(self.user_id,0))
        experience = self.player_state(session).get('experience',0)+q['playerExp']
        self.update_player_state(session, experience=experience)
        return changed

    @staticmethod
    def aggregate_rewards(rewards):
        totals = Counter()
        kinds = {}
        order = []
        for reward in rewards:
            code = reward['code']
            if code not in kinds:
                kinds[code] = reward.get('type') or 'ITEM'
                order.append(code)
            totals[code] += int(reward['num'])
        return [{
            'type': kinds[code], 'code': code, 'num': totals[code]
        } for code in order]

    def grant_items(self, session, wallet, rewards, now):
        totals = Counter()
        for reward in rewards:
            totals[reward['code']] += reward['num']
        items = []
        for code,amount in totals.items():
            if code=='PRESENTED_MONEY':
                wallet.free_sakuradite += amount
                quantity = wallet.free_sakuradite
            elif code=='GOLD':
                wallet.gold += amount
                quantity = wallet.gold
            else:
                item = session.get(UserGameItem,(self.user_id,code))
                if item is None:
                    item = UserGameItem(user_id=self.user_id,item_id=code,quantity=0)
                    session.add(item)
                item.quantity += amount
                quantity = item.quantity
            items.append({'itemId':code,'quantity':quantity,'environmentId':'COMMON','createdAt':now})
        return items

    def catalog_status(self):
        return self.data.story_catalog_status()

    def catalog_detail(self, quest_id):
        return self.data.battle_catalog_detail(quest_id)

    def normalize_skip_payload(self, session, payload):
        """Resolve omitted UI fields from the current local battle state."""
        normalized = copy.deepcopy(payload)
        if not isinstance(normalized, dict):
            raise BattleError('スキップ要求の形式が正しくありません。')
        if normalized.get('questId') is None:
            active = active_battle(session, self.user_id)
            latest = session.scalar(
                select(LocalBattle)
                .where(LocalBattle.user_id == self.user_id)
                .order_by(text('rowid DESC')).limit(1))
            quest_id = (active or {}).get('questId')
            if quest_id is None and latest is not None:
                quest_id = latest.quest_id
            if quest_id is None:
                raise BattleError('スキップ対象のクエストを特定できません。')
            normalized['questId'] = int(quest_id)
        normalized.setdefault('deckType', 'MAIN1')
        normalized.setdefault('usedDailyQuestDropBoostItem', False)
        if not normalized.get('userCardIdList') and not normalized.get(
                'userKnightmareFrameIdList'):
            pilot = session.scalar(select(UserPilot).where(
                UserPilot.user_id == self.user_id)
                .order_by(UserPilot.user_card_id).limit(1))
            kmf = session.scalar(select(UserKmf).where(
                UserKmf.user_id == self.user_id,
                UserKmf.is_in_storage.is_(False))
                .order_by(UserKmf.user_kmf_id).limit(1))
            if pilot is None or kmf is None:
                raise BattleError('スキップに使用できる編成がありません。')
            normalized['userCardIdList'] = [pilot.user_card_id]
            normalized['userKnightmareFrameIdList'] = [kmf.user_kmf_id]
        return normalized

    def skip(self, payload, request_id):
        # The original UI sends one POST per clear, each with its own AJAX
        # request ID. Identical formations must not deduplicate different clears.
        _validate_request_id(request_id)
        now = self.clock()
        with self.sessions() as session:
            session.execute(text('BEGIN IMMEDIATE'))
            payload = self.normalize_skip_payload(session, payload)
            quest_id = self.validate_payload(payload)
            if quest_id not in self.SUPPORTED_QUESTS:
                raise BattleError('ストーリークエストのスキップは未実装です。通常出撃してください。')
            fingerprint = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()).hexdigest()
            previous = session.scalar(select(LocalBattle).where(LocalBattle.user_id==self.user_id,
                                                                LocalBattle.request_id==request_id))
            if previous:
                if previous.status!='SKIPPED' or previous.request_hash!=fingerprint:
                    raise BattleError('Request ID was already used for another battle operation')
                return previous.finish_response
            if active_battle(session,self.user_id):
                raise BattleError('進行中のバトルを終了してからスキップしてください。')
            progress = self.progress(session,quest_id)
            if progress.get('bestQuestRank')!='S' or not all(progress.get('clearedMission%s'%n) for n in (1,2,3)):
                raise BattleError('クリアランクSかつミッションコンプリートでスキップが可能になります。')
            daily_definition = self.data.daily_quest(quest_id)
            if self.daily(session,quest_id)['dailyClearCount'] >= daily_definition['dailyType']['maxClearCount']:
                raise BattleError('本日のクリア回数上限に達しました。')
            pairs = self.owned_pairs(session,payload)
            wallet = session.get(UserWallet,self.user_id)
            cost = self.fixture(quest_id)['quest']['usedAtp']
            if wallet.stamina < cost:
                raise BattleError('スタミナが不足しています。')
            if skip_ticket_count(session,self.user_id,wallet) < 1:
                raise BattleError('クエストスキップチケットが不足しています。')
            use_drop_boost = bool(payload.get('usedDailyQuestDropBoostItem'))
            boost_item = session.get(
                UserGameItem, (self.user_id, 'DAILY_QUEST_DROP_BOOST'))
            if use_drop_boost and (not boost_item or boost_item.quantity < 1):
                raise BattleError('ドロップブーストアイテムが不足しています。')
            coefficient = self.drop_coefficient(now,quest_id)
            if use_drop_boost:
                coefficient *= 2
            rewards = self.data.daily_max_rewards(quest_id, coefficient)
            wallet.stamina -= cost
            wallet.stamina_updated_at = now
            if use_drop_boost:
                boost_item.quantity -= 1
            ticket = session.get(UserGameItem,(self.user_id,'SKIP_QUEST'))
            if ticket and ticket.quantity:
                ticket.quantity -= 1
            else:
                wallet.skip_tickets -= 1
            remaining_skip_items = ticket.quantity if ticket else 0
            changed = self.grant_experience(session,pairs,quest_id)
            items = self.grant_items(session,wallet,rewards,now.isoformat())
            if use_drop_boost:
                items.append({'itemId':'DAILY_QUEST_DROP_BOOST',
                              'quantity':boost_item.quantity,
                              'environmentId':'COMMON','createdAt':now.isoformat()})
            items.append({'itemId':'SKIP_QUEST','quantity':remaining_skip_items,
                          'environmentId':'COMMON','createdAt':now.isoformat()})
            result_id = uuid.uuid4().hex
            response = {'resultCode':'success','currentTime':now.isoformat(),'userQuestResultId':result_id,
                'battleResult':{'result':'SKIP','clearRank':'S','rewardList':rewards},
                'userQuestList':[progress],'userCardList':changed,'userItemList':items,
                'userStatusList':self.user_statuses(wallet,now)}
            record = LocalBattle(id=result_id,user_id=self.user_id,request_id=request_id,
                request_hash=fingerprint,quest_id=quest_id,period=now.date().isoformat(),
                status='SKIPPED',start_response={},drop_rewards={},finish_response=copy.deepcopy(response))
            session.add(record)
            session.flush()
            response['userDailyQuestList'] = [self.daily(session,quest_id)]
            record.finish_response = copy.deepcopy(response)
            session.commit()
            return response

    def start(self, payload, request_id=None):
        # The WebView generates a fresh header for each AJAX attempt. Active
        # formation identity additionally makes a lost response resumable.
        request_id = request_id if request_id is not None else uuid.uuid4().hex
        _validate_request_id(request_id)
        quest_id = self.validate_payload(payload)
        fingerprint = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        now = self.clock()
        with self.sessions() as session:
            session.execute(text('BEGIN IMMEDIATE'))
            previous = session.scalar(select(LocalBattle).where(LocalBattle.user_id==self.user_id,
                                                               LocalBattle.request_id==request_id))
            if previous:
                if previous.request_hash != fingerprint:
                    raise BattleError('Request ID was reused with another formation')
                if previous.status != 'ACTIVE':
                    raise BattleError('This start request has already been settled')
                return previous.start_response
            active = session.scalar(select(LocalBattle).where(LocalBattle.user_id==self.user_id,
                                                              LocalBattle.status=='ACTIVE'))
            if active:
                if active.request_hash == fingerprint:
                    return active.start_response
                raise BattleError('進行中のバトルがあります。同じ編成で再開してリタイアしてください。')
            daily_definition = self.data.daily_quest(quest_id)
            daily_type = ((daily_definition or {}).get('dailyType'))
            if daily_type and self.daily(session,quest_id)['dailyClearCount'] >= daily_type['maxClearCount']:
                raise BattleError('本日のクリア回数上限に達しました。')
            pairs = self.owned_pairs(session,payload)
            progress = self.progress(session,quest_id)
            try:
                battle = self.data.assemble(pairs,progress,quest_id=quest_id)
            except (KeyError, IndexError) as exc:
                raise BattleError('編成に必要な戦闘データを読み込めません。別のユニットを選んでください。') from exc
            wallet = session.get(UserWallet,self.user_id)
            cost = self.fixture(quest_id)['quest']['usedAtp']
            if wallet.stamina < cost:
                raise BattleError('スタミナが不足しています。')
            use_drop_boost = bool(payload.get('usedDailyQuestDropBoostItem'))
            boost_item = session.get(
                UserGameItem, (self.user_id, 'DAILY_QUEST_DROP_BOOST'))
            if use_drop_boost and (not boost_item or boost_item.quantity < 1):
                raise BattleError('ドロップブーストアイテムが不足しています。')
            drop_rewards = {}
            if daily_definition:
                coefficient = self.drop_coefficient(now,quest_id)
                if use_drop_boost:
                    coefficient *= 2
                bundle = copy.deepcopy(
                    self.data.daily_reward_bundle(quest_id))
                for reward in bundle:
                    reward['num'] = int(reward['num'] * coefficient)
                for wave in battle['questData']['waveData']:
                    for event in wave['waveEventData']:
                        event.pop('dropId', None)
                        drop_id = uuid.uuid4().hex
                        event['dropId'] = drop_id
                        drop_rewards[drop_id] = copy.deepcopy(bundle)
            if use_drop_boost:
                boost_item.quantity -= 1
            wallet.stamina -= cost
            wallet.stamina_updated_at = now
            result_id = uuid.uuid4().hex
            response = {'resultCode':'success','currentTime':now.isoformat(),'battle':battle,
                        'userCardList':[self.battle_card_data(p)
                                         for p,k in pairs],
                        'userQuestResultId':result_id,'userQuestList':[progress],
                        'userStatusList':self.user_statuses(wallet,now)}
            session.add(LocalBattle(id=result_id,user_id=self.user_id,request_id=request_id,
                request_hash=fingerprint,quest_id=quest_id,period=now.date().isoformat(),
                start_response=response,drop_rewards=drop_rewards,status='ACTIVE'))
            session.commit()
            return response

    def finish(self, result_id, result):
        if not isinstance(result, dict):
            raise BattleError('Expected a battle result object')
        now = self.clock().isoformat()
        with self.sessions() as session:
            session.execute(text('BEGIN IMMEDIATE'))
            record = session.get(LocalBattle,result_id)
            if record is None or record.user_id!=self.user_id:
                raise BattleError('Unknown local battle session')
            if record.status=='SKIPPED':
                raise BattleError('A skipped quest cannot be submitted as a native battle result')
            if record.status=='DONE':
                original = {k:v for k,v in record.finish_response['battleResult'].items()
                            if k != 'rewardList'}
                if original != result:
                    raise BattleError('This battle was already settled with a different result')
                return record.finish_response
            quest_id = record.quest_id
            fixture = self.fixture(quest_id)
            outcome = result.get('result')
            if outcome not in ('WIN','LOSE','RETIRE','RETIRED'):
                raise BattleError('Unsupported battle outcome')
            drops = result.get('dropIdList',[])
            if not isinstance(drops,list) or not all(isinstance(d,str) for d in drops) or len(drops)!=len(set(drops)) or any(d not in record.drop_rewards for d in drops):
                raise BattleError('Result contains invalid or duplicate drop identifiers')
            formation_pairs = [
                (p['userPilotId'], p['userKnightmareId'])
                for p in record.start_response['battle']['playerData']['pilotStatusData']]
            pairs = set(formation_pairs)
            report = result.get('battleResultDetailData')
            if report is None and outcome != 'WIN':
                report = {}
            if not isinstance(report, dict):
                raise BattleError('Invalid battle report')
            details = report.get('pilotResultData',[])
            if not isinstance(details,list) or len(details)>len(pairs):
                raise BattleError('Invalid pilot report')
            seen = set()
            for detail in details:
                if not isinstance(detail, dict):
                    raise BattleError('Invalid pilot report')
                pair = (detail.get('userPilotId'),detail.get('userKnightmareId'))
                if not all(isinstance(value, str) for value in pair):
                    raise BattleError('Invalid pilot report identifiers')
                if pair not in pairs or pair in seen:
                    raise BattleError('Pilot report does not match this battle formation')
                seen.add(pair)
                for key in ('totalDamage','receivedDamage','pilotSkillUseCount1','pilotSkillUseCount2','knightmareSkillUseCount'):
                    if type(detail.get(key,0)) is not int or not 0 <= detail.get(key,0) <= 2147483647:
                        raise BattleError('Invalid battle report counter')
            wallet = session.get(UserWallet,self.user_id)
            progress = self.progress(session,quest_id)
            rewards, changed_pilots = [], []
            if outcome=='WIN':
                qdata = record.start_response['battle']['questData']
                if qdata['winLoseConditionData']['condition'] not in (
                        'INVADED', 'INVADED_DESTROY_ALL_BOSS_1',
                        'INVADED_DESTROY_ALL_BOSS_2'):
                    raise BattleError('Unsupported battle win condition')
                expected = qdata['enemyNum']
                minimum = expected - int(qdata['winLoseConditionData']['parameters']) + 1
                defeats = result.get('defeatCount')
                if type(defeats) is not int or not minimum <= defeats <= expected:
                    raise BattleError('Defeat count does not satisfy the quest victory condition')
                if seen != pairs:
                    raise BattleError('Victory requires the complete battle formation report')
                if type(result.get('usedPlayerSkill')) is not bool or result.get('isRetryWeakened') is not False:
                    raise BattleError('Invalid player skill or unsupported retry report')
                rank = result.get('clearRank')
                # Exact WinLoseConditionInvaded.CalculateClearRank formula.
                expected_rank = 'S' if defeats == expected else ('A' if defeats >= (expected + minimum + 1)//2 else 'B')
                if rank != expected_rank:
                    raise BattleError('Invalid clear rank')
                rewards = []
                for drop_id in drops:
                    plan = record.drop_rewards[drop_id]
                    rewards.extend(copy.deepcopy(
                        plan if isinstance(plan, list) else [plan]))
                used_pilot_skill = sum(
                    d.get('pilotSkillUseCount1', 0)
                    + d.get('pilotSkillUseCount2', 0)
                    for d in details)
                mission_data = qdata['missionData']
                mission_codes = {
                    number: mission_data.get('missionCode%s' % number, '')
                    for number in (1, 2, 3)}
                for number in (1, 2, 3):
                    flag = result.get('isAchieveMission%s' % number)
                    if type(flag) is not bool:
                        raise BattleError('Mission flags must be booleans')
                    code = mission_codes[number]
                    parameters = mission_data.get('missionParameters%s' % number, '')
                    if not code:
                        continue
                    if code in ('UNIT_RETIRE', 'UNIT_WITHDRAW'):
                        pass
                    elif code == 'PILOT_SKILL':
                        threshold = int(parameters or 0)
                        if flag != (used_pilot_skill >= threshold):
                            raise BattleError('Pilot-skill mission does not match the battle report')
                    elif code == 'PLAYER_SKILL_UNUSED':
                        if flag != (not result['usedPlayerSkill']):
                            raise BattleError('Player-skill mission does not match the battle report')
                    else:
                        raise BattleError('Unsupported battle mission code')
                    progress['clearedMission%s' % number] |= flag
                if (mission_codes[1] == 'UNIT_RETIRE'
                        and mission_codes[2] == 'UNIT_RETIRE'
                        and result['isAchieveMission1']
                        and not result['isAchieveMission2']):
                    raise BattleError('Inconsistent unit-retirement missions')
                for achieved in 'BAS'[:'BAS'.index(rank)+1]:
                    key = 'reward%sReceivedAt'%achieved
                    if not progress.get(key):
                        amount = int(fixture['quest'].get('reward' + achieved, 0) or 0)
                        if amount > 0:
                            rewards.append({'type':'ITEM','code':'PRESENTED_MONEY',
                                            'num':amount})
                        progress[key] = now
                if all(progress['clearedMission%s'%n] for n in (1,2,3)) and not progress.get('rewardMissionCompleteReceivedAt'):
                    q = fixture['quest']
                    rewards.append({'type':'ITEM','code':q['questMissionCompleteItemId'],'num':q['questMissionCompleteItemNum']})
                    progress['rewardMissionCompleteReceivedAt'] = now
                if not fixture['quest'].get('dailyType'):
                    rewards.append({'type':'ITEM','code':'SKIP_QUEST','num':1})
                if progress.get('bestQuestRank') not in 'BAS' or 'BAS'.index(rank)>'BAS'.index(progress['bestQuestRank']):
                    progress['bestQuestRank'] = rank
                progress.update(questStatus='CLEARED',clearedAt=progress.get('clearedAt') or now,isNew=False)
                row = session.get(LocalBattleProgress,(self.user_id,quest_id))
                if row:
                    row.state = progress
                else:
                    session.add(LocalBattleProgress(user_id=self.user_id,quest_id=quest_id,state=progress))
                self.apply_quest_post_processors(session, quest_id)
                owned = [(session.scalar(select(UserPilot).where(
                    UserPilot.user_id==self.user_id,
                    UserPilot.user_card_id==pid)), None)
                    for pid, kid in formation_pairs]
                changed_pilots = self.grant_experience(session,owned,quest_id)
            else:
                wallet.stamina += record.start_response['battle']['questData']['returnStaminaOnFail']
            items = self.grant_items(session,wallet,rewards,now)
            output = copy.deepcopy(result)
            output['rewardList'] = rewards
            game_user = self.game_user_progress(session)
            response = {'resultCode':'success','currentTime':now,'battleResult':output,
                'gameUser':game_user,'floatingNotificationList':[],
                'userQuestList':[progress],'userCardList':changed_pilots,'userItemList':items,
                'userStatusList':self.user_statuses(wallet,now)}
            record.status = 'DONE'
            record.finish_response = copy.deepcopy(response)
            session.flush()
            response['userDailyQuestList'] = ([self.daily(session,quest_id)]
                if fixture['quest'].get('dailyType') else [])
            record.finish_response = copy.deepcopy(response)
            session.commit()
            return response


def active_battle(session, user_id):
    row = session.scalar(select(LocalBattle).where(LocalBattle.user_id == user_id,
                                                   LocalBattle.status == 'ACTIVE'))
    if row is None:
        return None
    q = row.start_response['battle']['questData']
    return {'userQuestResultId':row.id, 'questId':row.quest_id,
            'questName':q['questName'], 'returnStaminaOnFail':q['returnStaminaOnFail']}


def battle_state(session,user_id,service=None):
    rows = session.scalars(select(LocalBattleProgress).where(LocalBattleProgress.user_id==user_id)).all()
    progress = {r.quest_id:r.state for r in rows if r.quest_id}
    if service is not None:
        for quest_id in service.SUPPORTED_QUESTS:
            progress.setdefault(quest_id,service.initial_progress(quest_id))
    profile_state = next((r.state for r in rows if r.quest_id == 0), {})
    return {'userQuestList':list(progress.values()),
            'localActiveBattle':active_battle(session,user_id),
            'battleExperience':profile_state.get('experience',0),
            'tutorialId':profile_state.get('tutorialId','')}
