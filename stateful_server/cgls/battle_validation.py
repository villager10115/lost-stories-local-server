"""Reject incomplete native references before charging stamina or pushing a scene.

Mirrors reference boundaries in the preserved QuestBattleStartData validators.
It does not simulate combat or prove native rendering.
"""
import re
from .battle_data import BattleError


def validate_battle(battle):
    player, quest = battle['playerData'], battle['questData']
    def index(rows, key):
        result = {r[key]:r for r in rows}
        if len(result) != len(rows):
            raise BattleError('Duplicate native table key: ' + key)
        return result
    def combine(primary, secondary, key, label):
        result = index(primary, key)
        for row in secondary:
            previous = result.get(row[key])
            if previous is not None and previous != row:
                raise BattleError(
                    'Conflicting native %s: %s' % (label, row[key]))
            result[row[key]] = row
        return result
    effects = combine(player['affectorData'], quest['npcAffectorData'],
                     'affectorId', 'affector')
    ranges = combine(player['attackRangeData'], quest['npcAttackRangeData'],
                    'attackRangeId', 'attack range')
    priorities = combine(player['priorityData'], quest['npcPriorityData'],
                        'priorityId', 'target priority')
    pilots = combine(player['pilotSkillData'], quest['npcSkillData'],
                     'pilotSkillId', 'pilot skill')
    skills = combine(player['knightmareSkillData'],
                     quest['npcKnightmareSkillData'],
                     'knightmareSkillId', 'KMF skill')
    features = index(player['knightmareFeatureSkillData'], 'kmfFeatureSkillId')
    pfeatures = index(player['pilotFeatureSkillData'], 'pilotFeatureSkillId')
    transforms = index(player['transformDetailData'], 'id')
    units = index(player['knightmareStatusData'], 'userKnightmareId')
    traps = index(quest['gimmickData'], 'gimmickId')
    trap_ranges = index(quest['gimmickRangeData'], 'attackRangeId')
    def require(value, rows, label):
        if value and value not in rows:
            raise BattleError('Missing native %s: %s' % (label, value))
    for trap in traps.values():
        require(trap.get('rangeId'), trap_ranges, 'gimmick attack range')
    for placed in quest['placedGimmickData']:
        require(placed.get('gimmickId'), traps, 'placed gimmick')
        if not isinstance(placed.get('location'), dict):
            raise BattleError('Placed gimmick has no location')
    for pilot in player['pilotStatusData']:
        require(pilot['userKnightmareId'], units, 'paired KMF')
        require(pilot['priorityId'], priorities, 'target priority')
        for n in range(1,7):
            require(pilot.get('pilotSkillId%s' % n), pilots, 'pilot skill')
        for value in pilot['pilotFeatureSkillIds']:
            require(value, pfeatures, 'pilot feature')
    for kmf in list(units.values()) + list(transforms.values()):
        require(kmf['attackRangeId'], ranges, 'attack range')
        require(kmf['knightmareSkillId'], skills, 'KMF skill')
        for n in range(1,6):
            require(kmf.get('kmfFeatureSkillId%s' % n), features, 'KMF feature')
        for suffix in ('','2','3'):
            require(kmf.get('transformDetailId'+suffix), transforms, 'transform')
        for n in range(1,4):
            require(kmf.get('weaponChangeTransformDetailId%s' % n), transforms, 'union weapon form')
            require(kmf.get('weaponChangeUserKnightmareId%s' % n), units, 'owned weapon form')
        require(kmf.get('extendTransformDetailId'), transforms, 'extended transform')
    for npc in quest['npcStatusData']:
        require(npc.get('priorityId'), priorities, 'NPC target priority')
        require(npc.get('attackRangeId'), ranges, 'NPC attack range')
        require(npc.get('knightmareSkillId'), skills, 'NPC KMF skill')
        for n in range(1,7):
            require(npc.get('pilotSkillId%s' % n), pilots, 'NPC pilot skill')
    referenced_pilots = {p.get('pilotSkillId%s'%n) for p in player['pilotStatusData'] for n in range(1,7)}
    referenced_skills = {k['knightmareSkillId'] for k in list(units.values()) + list(transforms.values())}
    player_pilots = {r['pilotSkillId'] for r in player['pilotSkillData']}
    player_skills = {r['knightmareSkillId'] for r in player['knightmareSkillData']}
    if player_pilots - referenced_pilots or player_skills - referenced_skills:
        raise BattleError('Native skill table contains an unassociated player skill')
    for rows in (pilots, skills, features, pfeatures):
        for skill in rows.values():
            for key,value in skill.items():
                if re.fullmatch(r'affectorId\d+',key):
                    require(value,effects,'skill effect')
    for skill in skills.values():
        require(skill.get('attackRangeId'), ranges, 'skill attack range')
        if not any(value for key,value in skill.items() if re.fullmatch(r'affector\d+Entrainment',key)):
            # Field names are checked below from the retained serializer contract.
            if not any(value for key,value in skill.items() if 'entrainment' in key.lower()):
                raise BattleError('KMF skill has no entrainment effect')
    for effect in effects.values():
        require(effect.get('priorityId'), priorities, 'affector target priority')
