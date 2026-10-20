"""Cost and disclosure boundaries cannot be covered by guest boot tests."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

import review


class ReviewBoundaries(unittest.TestCase):
    def test_refreshing_phone_timestamp_does_not_buy_another_review(self):
        # USB polling is not new evidence; a model change is. Guest tests
        # cannot exercise the senior-inference cost boundary.
        packet = {'lanes': {}, 'phone_observation': {
            'checked_at': 'earlier', 'event_id': 'same', 'status': 'identified_n90'}}
        before = review.evidence_fingerprint(packet)
        packet['phone_observation']['checked_at'] = 'later'
        self.assertEqual(review.evidence_fingerprint(packet), before)
        packet['phone_observation']['status'] = 'other_model'
        self.assertNotEqual(review.evidence_fingerprint(packet), before)

    def test_attempt_budget_uses_auckland_day_and_spacing(self):
        # A UTC date rollover must not grant extra paid reviews in Auckland.
        t = datetime(2026, 10, 20, 23, tzinfo=ZoneInfo('Pacific/Auckland')).timestamp()
        self.assertFalse(review.budget_ok([{'started': t - 3600}], t))
        self.assertTrue(review.budget_ok([{'started': t - 2 * 3600}], t))
        attempts = [{'started': t - hours * 3600, 'state': 'failed'}
                    for hours in range(22, 2, -2)]
        self.assertTrue(review.budget_ok(attempts[:-1], t))
        self.assertFalse(review.budget_ok(attempts, t))
        # A fresh Auckland date grants slots, but cannot bypass inter-review spacing.
        self.assertTrue(review.budget_ok(attempts, t + 2 * 3600))
        self.assertFalse(review.budget_ok([{'started': t + 1800}], t + 3600))

    def test_packet_refuses_symlink_and_private_key(self):
        # Real outbound leakage cannot safely be tested with a real secret.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'worker'
            root.mkdir()
            outside = Path(temp) / 'outside'
            outside.write_text('outside fixture')
            (root / 'link').symlink_to(outside)
            (root / 'key').write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nfixture')
            self.assertIn('omitted', review.read_text(root, 'link'))
            self.assertIn('omitted', review.read_text(root, 'key'))

    def test_unknown_lane_cannot_select_a_publication_target(self):
        # Reviewer output must not choose another repository or issue target.
        result = {'reviews': [{'lane': 'foreign', 'decision': 'continue',
                               'findings': [], 'next_action': 'none'}]}
        with self.assertRaises(ValueError):
            review.validate(result)


if __name__ == '__main__':
    unittest.main()
