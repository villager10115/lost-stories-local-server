from pathlib import Path
import tempfile
import unittest

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cgls.bootstrap import normalize_kmf_revision_classes
from cgls.db import create_database_engine, create_session_factory, initialize_database
from cgls.models import User, UserDeck, UserItem, UserKmf, UserPilot, UserWallet


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_database_engine(Path(self.directory.name) / "test.sqlite")
        initialize_database(self.engine)
        self.session = create_session_factory(self.engine)()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_state_is_persistent_and_related(self):
        user = User(display_name="local")
        user.wallet = UserWallet(
            free_sakuradite=100, paid_sakuradite=20, gold=5000,
            stamina=10, max_stamina=10,
        )
        user.pilots.append(UserPilot(
            user_card_id="card-1", mst_pilot_id=101001, mst_chara_id=101,
            level=5, skill_levels=[1, 2], unlocked_feature_ids=[],
        ))
        user.kmfs.append(UserKmf(
            user_kmf_id="kmf-1", mst_kmf_id=1001, upgrade_ranks={"hp": 2},
        ))
        user.items.append(UserItem(mst_item_id=1, count=3))
        user.decks.append(UserDeck(
            deck_no=1, deck_name="main", slots=[{"pilot": "card-1"}],
        ))
        self.session.add(user)
        self.session.commit()
        user_id = user.id
        self.session.close()

        self.session = create_session_factory(self.engine)()
        loaded = self.session.get(User, user_id)
        self.assertEqual(loaded.wallet.free_sakuradite, 100)
        self.assertEqual(loaded.pilots[0].skill_levels, [1, 2])
        self.assertEqual(loaded.kmfs[0].upgrade_ranks, {"hp": 2})
        self.assertEqual(loaded.kmfs[0].revision_class, 1)
        self.assertEqual(loaded.items[0].count, 3)
        self.assertEqual(loaded.decks[0].slots, [{"pilot": "card-1"}])

    def test_constraints_and_cascade(self):
        user = User()
        user.wallet = UserWallet(
            free_sakuradite=-1, paid_sakuradite=0, gold=0,
            stamina=0, max_stamina=0,
        )
        self.session.add(user)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

        user = User()
        user.pilots.append(UserPilot(
            mst_pilot_id=1, level=1, limit_break=0, skill_levels=[],
            unlocked_feature_ids=[],
        ))
        self.session.add(user)
        self.session.commit()
        self.session.delete(user)
        self.session.commit()
        self.assertEqual(
            self.session.execute(select(UserPilot)).scalars().all(), []
        )

    def test_normalizes_kmf_revision_classes_from_progress(self):
        user = User()
        for index, revision in enumerate((0, 3, 6, 9), start=1):
            user.kmfs.append(UserKmf(
                user_kmf_id="kmf-%d" % index,
                mst_kmf_id=2600 + index,
                revision=revision,
                revision_class=1,
            ))
        self.session.add(user)
        self.session.commit()

        normalized = normalize_kmf_revision_classes(
            create_session_factory(self.engine)
        )

        self.assertEqual(normalized, 3)
        self.session.expire_all()
        kmfs = self.session.execute(
            select(UserKmf).order_by(UserKmf.user_kmf_id)
        ).scalars().all()
        self.assertEqual(
            [kmf.revision_class for kmf in kmfs],
            [1, 2, 3, 4],
        )

    def test_rejects_invalid_kmf_revision_class(self):
        user = User()
        user.kmfs.append(UserKmf(
            user_kmf_id="kmf-invalid",
            mst_kmf_id=2604,
            revision=0,
            revision_class=0,
        ))
        self.session.add(user)
        with self.assertRaises(IntegrityError):
            self.session.commit()


if __name__ == "__main__":
    unittest.main()
