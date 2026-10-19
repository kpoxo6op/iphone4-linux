"""Cost-boundary tests; QEMU cannot exercise the host's inference scheduler."""
from datetime import datetime, timezone
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


if __name__ == '__main__':
    unittest.main()
