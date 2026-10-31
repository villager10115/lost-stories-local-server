"""Assemble every preserved main-story definition, never captured player progress."""
import argparse
import copy
import hashlib
import json
from pathlib import Path


def extract_catalog(definitions_path, locations_path):
    definitions_path, locations_path = Path(definitions_path), Path(locations_path)
    source = json.loads(definitions_path.read_text('utf8'))
    quests = sorted(copy.deepcopy(source['quests']), key=lambda row: row['questId'])
    chapters = sorted(copy.deepcopy(source['chapters']), key=lambda row: -row['chapterId'])
    assert len({row['questId'] for row in quests}) == len(quests)
    assert len({row['chapterId'] for row in chapters}) == len(chapters)
    chapter_ids = {row['chapterId'] for row in chapters}
    assert all(row['questType'] == 'MAIN' and row['chapterId'] in chapter_ids for row in quests)
    location_ids = {row['locationId'] for row in quests}
    locations = [row for row in json.loads(locations_path.read_text('utf8'))['locationList']
                 if row['locationId'] in location_ids]
    assert {row['locationId'] for row in locations} == location_ids
    assert all({'mapDataNo', 'x', 'y', 'imageNo'} <= row.keys() for row in locations)
    gaps = []
    for chapter in chapters:
        entries = [row for row in quests if row['chapterId'] == chapter['chapterId']]
        actual = {'storyNum': sum(row['onlyStory'] for row in entries),
                  'battleNum': sum(not row['onlyStory'] and row['difficulty'] != 'EXTRA' for row in entries),
                  'extraBattleNum': sum(not row['onlyStory'] and row['difficulty'] == 'EXTRA' for row in entries)}
        missing = {key: chapter.get(key, 0) - value for key, value in actual.items()
                   if chapter.get(key, 0) > value}
        if missing:
            gaps.append({'chapterId': chapter['chapterId'], 'counts': missing})
    return {'quests': quests, 'chapters': chapters, 'locations': locations,
            'sources': source['sources'], 'sourceEvidence': source.get('sourceEvidence', []),
            'inputHashes': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (definitions_path, locations_path)},
            'coverage': {'chapterCount': len(chapters), 'questCount': len(quests),
                         'locationCount': len(locations), 'definitionGaps': gaps}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('definitions', type=Path)
    parser.add_argument('locations', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = extract_catalog(args.definitions, args.locations)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result['coverage']))
