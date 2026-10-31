"""Persistent story-only completion using preserved quest definitions."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictInt
from sqlalchemy import text, select, String, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .gacha_service import ensure_local_user
from .db import Base


class LocalStoryProgress(Base):
    __tablename__ = 'local_story_progress'
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey('users.id'), primary_key=True)
    quest_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[dict] = mapped_column(JSON)


def story_state(session, user_id):
    return [copy.deepcopy(row.state) for row in session.scalars(
        select(LocalStoryProgress).where(LocalStoryProgress.user_id == user_id)).all()]


class StoryEndRequest(BaseModel):
    questId: StrictInt

    class Config:
        extra = 'forbid'


class StoryService:
    def __init__(self, sessions, profile, catalog=None):
        self.sessions, self.profile = sessions, profile
        catalog = catalog or Path(__file__).resolve().parents[1] / 'fixtures/main_story_catalog.json'
        data = json.loads(Path(catalog).read_text(encoding='utf8'))
        self.quests = {q['questId']: q for q in data['quests']}

    def complete(self, quest_id):
        quest = self.quests.get(quest_id)
        if not quest or not quest.get('onlyStory') or not quest.get('startStoryNo'):
            raise ValueError('再生可能なストーリークエストではありません。')
        reward = quest.get('rewardOnlyStory', 0)
        if type(reward) is not int or reward < 0:
            raise ValueError('Invalid preserved story reward')
        with self.sessions() as session:
            user = ensure_local_user(session, profile=self.profile)
            user_id = user.id
            session.commit()
            session.expire_all()
            session.execute(text('BEGIN IMMEDIATE'))
            user = ensure_local_user(session, profile=self.profile)
            saved = session.get(LocalStoryProgress, (user_id, quest_id))
            now = datetime.now(timezone.utc).isoformat()
            state = copy.deepcopy(saved.state) if saved else {
                'questId': quest_id, 'quest': copy.deepcopy(quest),
                'questStatus': 'OPENED', 'bestQuestRank': 'NONE',
                'isNew': False, 'createdAt': now,
                'clearedMission1': False, 'clearedMission2': False,
                'clearedMission3': False,
            }
            if state.get('questStatus') != 'CLEARED':
                # The retained client completes story-only quests before
                # pushAdventure. Primary key + writer lock makes retries safe.
                user.wallet.free_sakuradite += reward
                state.update(questStatus='CLEARED', clearedAt=now, isNew=False)
                if saved:
                    saved.state = state
                else:
                    session.add(LocalStoryProgress(user_id=user_id, quest_id=quest_id, state=state))
            session.commit()
            return {'resultCode': 'success', 'userQuestList': [state]}


def install_routes(app, sessions, profile):
    LocalStoryProgress.__table__.create(bind=app.state.engine, checkfirst=True)
    service = StoryService(sessions, profile)

    @app.post('/api/quest/story/end')
    def story_end(request: StoryEndRequest):
        try:
            return service.complete(request.questId)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={
                'resultCode': 'error', 'title': 'ストーリー', 'errorTxt': str(exc)})
