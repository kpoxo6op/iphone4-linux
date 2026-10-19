"""Cost-boundary tests; QEMU cannot exercise the host's inference scheduler."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import control


class BillingWindow(unittest.TestCase):
    def test_utc_boundaries_and_weekend(self):
        # Catches timezone/endpoint mistakes that could incur peak billing.
        cases = [('2026-10-19T00:54:59', True), ('2026-10-19T00:55:00', False),
                 ('2026-10-19T01:00:00', False), ('2026-10-19T03:59:59', False),
                 ('2026-10-19T04:00:00', True), ('2026-10-19T05:55:00', False),
                 ('2026-10-19T10:00:00', True), ('2026-10-24T01:30:00', True),
                 ('2026-10-25T09:00:00', True)]
        for stamp, expected in cases:
            with self.subTest(stamp=stamp):
                self.assertEqual(control.off_peak(datetime.fromisoformat(stamp)
                                 .replace(tzinfo=timezone.utc)), expected)

    def test_watchdog_interrupts_only_our_active_sessions(self):
        # Catches accidentally leaving paid work running or stopping other work.
        cfg = {'deadline': float('inf'), 'workers': [
            {'session': 'ours', 'path': '/work'}, {'session': 'idle', 'path': '/work'}]}
        with patch.object(control, 'off_peak', return_value=False), \
             patch.object(control, 'api', return_value={'ours': {}, 'unrelated': {}}), \
             patch.object(control, 'interrupt') as stop:
            control.gate(cfg)
            stop.assert_called_once_with(cfg['workers'][0])

    def test_review_feedback_cannot_start_inference_during_peak(self):
        # A new correction must not bypass the cost boundary while a lane waits.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.opencode').mkdir()
            (root / '.opencode/review-feedback.json').write_text(json.dumps({
                'id': 'new-review', 'decision': 'changes_requested'}))
            cfg = {'workers': [{'name': 'qemu', 'path': str(root),
                                 'session': 'ours', 'state': 'awaiting_review'}]}
            with patch.object(control, 'off_peak', return_value=False), \
                 patch.object(control, 'api', return_value={}) as api, \
                 patch.object(control, 'save'):
                control.tick(cfg)
                api.assert_called_once_with('GET', '/api/session/active')
                self.assertEqual(cfg['workers'][0]['state'], 'waiting_off_peak')


if __name__ == '__main__':
    unittest.main()
