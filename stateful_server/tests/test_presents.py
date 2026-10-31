from pathlib import Path
import tempfile
import unittest

from sqlalchemy import select

from cgls.db import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from cgls.models import User, UserPresent, UserWallet
from cgls.presents import (
    PresentError,
    grant_present,
    pending_present_count,
    present_page,
    receive_presents,
)


class PresentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_database_engine(
            Path(self.directory.name) / "test.sqlite")
        initialize_database(self.engine)
        self.session_factory = create_session_factory(self.engine)
        self.session = self.session_factory()
        self.user = User(display_name="local")
        self.user.wallet = UserWallet(
            free_sakuradite=300,
            paid_sakuradite=0,
            gold=1000,
            skip_tickets=0,
            stamina=135,
            max_stamina=135,
        )
        self.session.add(self.user)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_grant_receive_and_history_are_persistent(self):
        row = grant_present(
            self.session,
            self.user.id,
            "PRESENTED_MONEY",
            10000,
            "local test",
        )
        self.assertEqual(pending_present_count(self.session, self.user.id), 1)

        listing = present_page(self.session, self.user.id)
        self.assertEqual(listing["presentCount"], 1)
        self.assertEqual(listing["presentList"][0]["id"], row.present_id)
        self.assertEqual(listing["presentList"][0]["quantity"], 10000)

        receipt = receive_presents(
            self.session,
            self.user.id,
            present_ids=[row.present_id],
        )
        self.assertEqual(receipt["receivedIds"], [row.present_id])
        self.assertEqual(receipt["freeSakuradite"], 10300)
        self.assertEqual(receipt["presentCount"], 0)
        self.assertEqual(pending_present_count(self.session, self.user.id), 0)

        history = present_page(
            self.session, self.user.id, history=True)
        self.assertEqual(history["presentCount"], 1)
        self.assertIsNotNone(history["presentList"][0]["receivedAt"])

        replay = receive_presents(
            self.session,
            self.user.id,
            present_ids=[row.present_id],
        )
        self.assertTrue(replay["failed"])
        self.assertEqual(
            self.session.get(UserWallet, self.user.id).free_sakuradite,
            10300,
        )

    def test_receive_all_is_atomic_and_rejects_invalid_grants(self):
        grant_present(self.session, self.user.id, "PRESENTED_MONEY", 300)
        grant_present(self.session, self.user.id, "PRESENTED_MONEY", 3000)
        receipt = receive_presents(
            self.session, self.user.id, receive_all=True, total=2)
        self.assertEqual(len(receipt["receivedIds"]), 2)
        self.assertEqual(receipt["freeSakuradite"], 3600)
        self.assertEqual(
            len(self.session.execute(select(UserPresent)).scalars().all()), 2)

        with self.assertRaises(PresentError):
            grant_present(self.session, self.user.id, "UNKNOWN", 1)
        with self.assertRaises(PresentError):
            grant_present(self.session, self.user.id, "PRESENTED_MONEY", 0)


if __name__ == "__main__":
    unittest.main()
