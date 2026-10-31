"""Official formation and story routes for the loopback page server."""
import json

from deck_store import DeckStoreError, _flatten_deck


PATHS = {'/api/deck/save', '/api/deck/saveList', '/api/deck/set/name',
         '/api/quest/story/end', '/api/knightmareFrameCustomize/select'}


def handle(handler, path, raw_body):
    if path not in PATHS:
        return False
    if not handler.page_session_ok():
        handler.respond(403, {'error': 'Invalid local session'})
        return True
    if handler.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
        handler.respond(400, {'error': 'Expected JSON'})
        return True
    if path == '/api/quest/story/end':
        handler.forward_gacha(raw_body, target_path=path)
        return True
    server = handler.server
    if server.decks is None:
        handler.respond(503, {'error': 'No local deck store configured'})
        return True
    try:
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError('Expected object')
        if path == '/api/knightmareFrameCustomize/select':
            if set(payload) != {'userKnightmareFrameCustomizeId'}:
                raise ValueError('Expected one owned weapon ID')
            models = server.account_models()
            weapon = next((row for row in models.get('userKnightmareFrameCustomizeList', [])
                if row['userKnightmareFrameCustomizeId'] == payload['userKnightmareFrameCustomizeId']), None)
            if weapon is None or weapon.get('selected') is not True:
                raise ValueError('Weapon is not an owned selected customization')
            # The local inventory currently owns one customization per KMF.
            # Closing the official detail view reselects that same weapon.
            handler.respond(200, {'resultCode': 'success',
                'userKnightmareFrameCustomizeList': [weapon],
                'userKnightmareFrameList': models.get('userKnightmareFrameList', [])})
            return True
        account = server.account or 'local-account'
        cards, kmfs = server.owned_ids()
        if path == '/api/deck/set/name':
            rows = [server.decks.rename(account, payload.get('deckType'), payload.get('name'))]
        else:
            requests = payload.get('userDeckInfoList') if path.endswith('saveList') else [payload]
            rows = server.decks.save_many(account, requests, owned_cards=cards, owned_kmfs=kmfs)
        models = server.account_models()
        response = {'resultCode': 'success', 'userDeckList': [
            _flatten_deck(row['deckType'], row['slots'], row.get('name'), row['createdAt']) for row in rows],
            'userCardList': models.get('userCardList', []),
            'userKnightmareFrameList': models.get('userKnightmareFrameList', [])}
        if len(rows) == 1:
            response['deck'] = rows[0]
        handler.respond(200, response)
    except (ValueError, TypeError, UnicodeError, DeckStoreError) as exc:
        handler.respond(400, {'resultCode': 'error', 'title': '編成エラー', 'errorTxt': str(exc)})
    return True
