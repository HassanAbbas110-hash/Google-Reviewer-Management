import tempfile
import unittest
from pathlib import Path

from reviewer.core import Store, decision


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'queue.db'
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_is_unchanged(self):
        self.assertEqual(self.store.ingest('a', '1', 'Great', 5), 'pending')
        self.assertEqual(self.store.ingest('a', '1', 'Great', 5), 'unchanged')

    def test_businesses_are_isolated(self):
        self.store.ingest('a', '1', 'Great', 5)
        self.store.ingest('b', '1', 'Poor', 1)
        self.assertEqual(self.store.get('a', '1')['text'], 'Great')
        self.assertEqual(self.store.get('b', '1')['text'], 'Poor')

    def test_changed_rating_requires_reassessment(self):
        self.store.ingest('a', '1', 'Okay', 5)
        self.assertEqual(self.store.ingest('a', '1', 'Okay', 2), 'needs_approval')

    def test_existing_reply_is_preserved(self):
        self.assertEqual(self.store.ingest('a', '1', 'Great', 5, 'Staff reply'), 'already_replied')
        self.assertEqual(self.store.ingest('a', '1', 'Edited', 4, 'Staff reply'), 'already_replied')

    def test_queue_survives_restart(self):
        self.store.ingest('a', '1', 'Great', 5)
        self.assertEqual(Store(self.path).get('a', '1')['state'], 'pending')

    def test_invalid_rating_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.ingest('a', '1', 'Review', 0)

    def test_publication_fails_closed(self):
        base = dict(consent=True, facts_approved=True, auto_enabled=True, risk='routine', valid=True)
        self.assertEqual(decision(**base), 'eligible')
        for field in ('consent', 'facts_approved', 'auto_enabled', 'valid'):
            with self.subTest(field=field):
                self.assertNotEqual(decision(**{**base, field: False}), 'eligible')
        for risk in ('sensitive', 'unknown', 'complaint', ''):
            self.assertEqual(decision(**{**base, 'risk': risk}), 'needs_approval')
        self.assertEqual(decision(**base, existing_reply='Human reply'), 'already_replied')


if __name__ == '__main__':
    unittest.main()
