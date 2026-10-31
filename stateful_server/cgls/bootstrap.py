from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .kmf_rules import revision_class_for_revision
from .models import (
    User,
    UserBootstrapState,
    UserDeck,
    UserGameItem,
    UserKmf,
    UserPilot,
    UserWallet,
    LocalBattleProgress,
)


@dataclass(frozen=True)
class StarterPair:
    card_id: int
    kmf_id: int
    customization_id: Optional[int] = None


@dataclass(frozen=True)
class StarterProfile:
    profile_id: str = "empty"
    profile_version: int = 1
    tutorial_id: str = ""
    display_name: str = "local"
    free_sakuradite: int = 0
    paid_sakuradite: int = 0
    gold: int = 0
    skip_tickets: int = 0
    stamina: int = 0
    max_stamina: int = 0
    items: dict[str, int] = field(default_factory=dict)
    starter_pairs: tuple[StarterPair, ...] = ()

    @classmethod
    def empty(cls) -> "StarterProfile":
        return cls()

    @classmethod
    def from_file(cls, filename: Path | str) -> "StarterProfile":
        path = Path(filename)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Starter profile must be an object")

        wallet = data.get("wallet") or {}
        items = data.get("items") or {}
        pairs = data.get("starterPairs") or []
        if not isinstance(wallet, dict) or not isinstance(items, dict):
            raise ValueError("Starter wallet and items must be objects")
        if not isinstance(pairs, list):
            raise ValueError("Starter pairs must be a list")

        def nonnegative_int(value: Any, name: str) -> int:
            result = int(value)
            if result < 0:
                raise ValueError("%s must be nonnegative" % name)
            return result

        parsed_pairs = []
        seen_cards = set()
        seen_kmfs = set()
        for row in pairs:
            if not isinstance(row, dict):
                raise ValueError("Starter pair must be an object")
            card_id = int(row["cardId"])
            kmf_id = int(row["kmfId"])
            customization_id = row.get("customizationId")
            if customization_id is not None:
                customization_id = int(customization_id)
            if card_id <= 0 or kmf_id <= 0:
                raise ValueError("Starter IDs must be positive")
            if card_id in seen_cards or kmf_id in seen_kmfs:
                raise ValueError("Starter pairs contain duplicate IDs")
            seen_cards.add(card_id)
            seen_kmfs.add(kmf_id)
            parsed_pairs.append(
                StarterPair(card_id, kmf_id, customization_id)
            )

        parsed_items = {
            str(item_id): nonnegative_int(quantity, "item quantity")
            for item_id, quantity in items.items()
        }
        return cls(
            profile_id=str(data.get("profileId") or "local-starter"),
            profile_version=int(data.get("profileVersion") or 1),
            tutorial_id=str(data.get("tutorialId") or ""),
            display_name=str(data.get("displayName") or "Commander"),
            free_sakuradite=nonnegative_int(
                wallet.get("free_sakuradite", 0), "free_sakuradite"
            ),
            paid_sakuradite=nonnegative_int(
                wallet.get("paid_sakuradite", 0), "paid_sakuradite"
            ),
            gold=nonnegative_int(wallet.get("gold", 0), "gold"),
            skip_tickets=nonnegative_int(
                wallet.get("skip_tickets", 0), "skip_tickets"
            ),
            stamina=nonnegative_int(wallet.get("stamina", 0), "stamina"),
            max_stamina=nonnegative_int(
                wallet.get("max_stamina", 0), "max_stamina"
            ),
            items=parsed_items,
            starter_pairs=tuple(parsed_pairs),
        )


def normalize_kmf_revision_classes(session_factory) -> int:
    """Repair stored presentation classes from canonical revision progress."""
    with session_factory() as session:
        updated = 0
        for kmf in session.execute(select(UserKmf)).scalars():
            expected = revision_class_for_revision(kmf.revision)
            if kmf.revision_class != expected:
                kmf.revision_class = expected
                updated += 1
        session.commit()
        return updated


DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / "fixtures" / "new_account.json"


def load_default_profile() -> StarterProfile:
    if not DEFAULT_PROFILE.is_file():
        return StarterProfile.empty()
    return StarterProfile.from_file(DEFAULT_PROFILE)


def _seed_starter_state(
    session: Session,
    user: User,
    profile: StarterProfile,
) -> None:
    wallet = user.wallet
    if wallet is None:
        wallet = UserWallet(
            user_id=user.id,
            free_sakuradite=profile.free_sakuradite,
            paid_sakuradite=profile.paid_sakuradite,
            gold=profile.gold,
            skip_tickets=profile.skip_tickets,
            stamina=profile.stamina,
            max_stamina=profile.max_stamina,
        )
        user.wallet = wallet
        session.add(wallet)
    elif not user.bootstrap_state:
        wallet.free_sakuradite = max(
            wallet.free_sakuradite, profile.free_sakuradite
        )
        wallet.paid_sakuradite = max(
            wallet.paid_sakuradite, profile.paid_sakuradite
        )
        wallet.gold = max(wallet.gold, profile.gold)
        wallet.skip_tickets = max(
            wallet.skip_tickets, profile.skip_tickets
        )
        wallet.stamina = max(wallet.stamina, profile.stamina)
        wallet.max_stamina = max(
            wallet.max_stamina, profile.max_stamina
        )

    owned_cards = {
        row.mst_pilot_id
        for row in session.execute(
            select(UserPilot).where(UserPilot.user_id == user.id)
        ).scalars()
    }
    owned_kmfs = {
        row.mst_kmf_id
        for row in session.execute(
            select(UserKmf).where(UserKmf.user_id == user.id)
        ).scalars()
    }
    slots = []
    for pair in profile.starter_pairs:
        if pair.card_id not in owned_cards:
            pilot = UserPilot(
                user_id=user.id,
                user_card_id=str(uuid.uuid4()),
                mst_pilot_id=pair.card_id,
                mst_chara_id=pair.card_id // 1000,
                level=1,
                skill_levels=[],
                unlocked_feature_ids=[],
            )
            session.add(pilot)
            owned_cards.add(pair.card_id)
        else:
            pilot = session.execute(
                select(UserPilot).where(
                    UserPilot.user_id == user.id,
                    UserPilot.mst_pilot_id == pair.card_id,
                )
            ).scalars().first()

        if pair.kmf_id not in owned_kmfs:
            kmf = UserKmf(
                user_id=user.id,
                user_kmf_id=str(uuid.uuid4()),
                mst_kmf_id=pair.kmf_id,
                customization_id=pair.customization_id,
                revision_class=1,
            )
            session.add(kmf)
            owned_kmfs.add(pair.kmf_id)
        else:
            kmf = session.execute(
                select(UserKmf).where(
                    UserKmf.user_id == user.id,
                    UserKmf.mst_kmf_id == pair.kmf_id,
                )
            ).scalars().first()

        if pilot is not None and kmf is not None:
            slots.append({
                "pilot": pilot.user_card_id,
                "kmf": kmf.user_kmf_id,
            })

    for item_id, quantity in profile.items.items():
        row = session.get(UserGameItem, (user.id, item_id))
        if row is None:
            session.add(UserGameItem(
                user_id=user.id,
                item_id=item_id,
                quantity=quantity,
            ))
        else:
            row.quantity = max(row.quantity, quantity)

    if slots:
        deck = session.get(UserDeck, (user.id, 1))
        if deck is None:
            session.add(UserDeck(
                user_id=user.id,
                deck_no=1,
                deck_name="Knights1",
                slots=slots,
            ))
        elif not deck.slots:
            deck.slots = slots

    if profile.tutorial_id and session.get(
            LocalBattleProgress, (user.id, 0)) is None:
        session.add(LocalBattleProgress(
            user_id=user.id, quest_id=0,
            state={'experience': 0, 'tutorialId': profile.tutorial_id}))
    session.add(UserBootstrapState(
        user_id=user.id,
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
    ))


def ensure_local_user(
    session: Session,
    display_name: Optional[str] = None,
    profile: Optional[StarterProfile] = None,
) -> User:
    profile = profile or load_default_profile()
    user = session.execute(
        select(User).order_by(User.created_at)
    ).scalars().first()
    if user is not None:
        if user.bootstrap_state is None:
            session.refresh(user)
            if (
                not user.pilots
                and not user.kmfs
                and not user.decks
            ):
                _seed_starter_state(session, user, profile)
                session.commit()
            else:
                session.add(UserBootstrapState(
                    user_id=user.id,
                    profile_id="legacy-existing",
                    profile_version=0,
                ))
                session.commit()
        return user

    user = User(display_name=display_name or profile.display_name)
    session.add(user)
    session.flush()
    _seed_starter_state(session, user, profile)
    session.commit()
    return user


__all__ = [
    "StarterPair",
    "StarterProfile",
    "ensure_local_user",
    "load_default_profile",
]
