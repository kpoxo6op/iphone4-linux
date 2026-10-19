"""Cost and disclosure boundaries cannot be covered by guest boot tests."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

import review


class ReviewBoundaries(unittest.TestCase):
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
