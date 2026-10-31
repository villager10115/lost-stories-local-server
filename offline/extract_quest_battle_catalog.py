"""Extract every battle quest definition from a retained GachaTop response."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


DEFAULT_SOURCE = Path(
    'D:/LostStories_Preservation_20261018/'
    'gacha-capture-live-1905/bodies/'
    '_api_page_GachaTop-698c483509f68c6b.body'
)
DEFAULT_OUTPUT = Path('D:/codegeass/stateful_server/fixtures/'
                      'all_quest_catalog.json')


def extract(source):
    raw = source.read_bytes()
    response = json.loads(raw.decode('utf-8'))
    if response.get('resultCode') != 'success':
        raise ValueError('Source response is not successful')
    quests = []
    indexes = {}
    for progress in response.get('userQuestList', []):
        quest = progress.get('quest')
        if not isinstance(quest, dict) or not isinstance(quest.get('questId'), int):
            continue
        quest_id = quest['questId']
        previous = indexes.get(quest_id)
        if previous is not None and previous != quest:
            raise ValueError('Conflicting quest definition: %s' % quest_id)
        if previous is None:
            indexes[quest_id] = quest
            quests.append(quest)
    if not quests:
        raise ValueError('No quest definitions found')
    by_type = Counter(quest.get('questType') for quest in quests)
    battles_by_type = Counter(
        quest.get('questType') for quest in quests
        if not quest.get('onlyStory'))
    story_by_type = Counter(
        quest.get('questType') for quest in quests
        if quest.get('onlyStory'))
    return {
        'schemaVersion': 1,
        'source': {
            'path': source.as_posix(),
            'sha256': hashlib.sha256(raw).hexdigest(),
            'currentTime': response.get('currentTime'),
        },
        'counts': {
            'all': len(quests),
            'battles': sum(battles_by_type.values()),
            'storyOnly': sum(story_by_type.values()),
            'byQuestType': dict(sorted(
                by_type.items(), key=lambda item: str(item[0]))),
            'battlesByQuestType': dict(sorted(
                battles_by_type.items(), key=lambda item: str(item[0]))),
            'storyOnlyByQuestType': dict(sorted(
                story_by_type.items(), key=lambda item: str(item[0]))),
        },
        'quests': quests,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = extract(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )
    temporary.replace(args.output)
    print(json.dumps({
        'output': str(args.output),
        'bytes': args.output.stat().st_size,
        **payload['counts'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
