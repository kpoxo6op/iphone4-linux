"""Cost boundaries cannot safely be exercised by spending real money."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import control


FREE = dict(control.MODEL, enabled=True, status='active', variants=[{'id': 'max'}],
            cost=[{'input': 0, 'output': 0, 'cache': {'read': 0, 'write': 0}}])


class FreeWorkers(unittest.TestCase):
    def test_unavailable_or_newly_priced_route_is_rejected(self):
        # A provider price/variant change must not turn continuous work into paid work.
        for change in ({'enabled': False}, {'variants': [{'id': 'high'}]},
                       {'cost': []}, {'cost': [{'input': 0}]},
                       {'cost': [{'input': 0, 'output': 0.01}]},
                       {'cost': [{'input': 0, 'output': 0, 'cache': {'read': 0.1}}]},
                       {'providerID': 'deepseek'}):
            model = deepcopy(FREE)
            model.update(change)
            with self.subTest(change=change), patch.object(control, 'api', return_value=[model]):
                self.assertIsNotNone(control.free_route_error())
        with patch.object(control, 'api', side_effect=TimeoutError):
            self.assertIsNotNone(control.free_route_error())

    def test_free_work_survives_former_peak_hours_and_old_expiry(self):
        # No clock time may stop an approved free session with an ongoing run.
        cfg = {'deadline': None, 'workers': [{'session': 'ours', 'path': '/work'}]}
        def api(method, path):
            return {'/api/model': [FREE], '/api/session/active': {'ours': {}},
                    '/api/session/ours': {'model': control.MODEL},
                    '/api/session/ours/permission': []}[path]
        for stamp in ('2026-10-20T01:30:00', '2026-10-20T06:30:00', '2027-01-01T06:30:00'):
            now = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp()
            with patch.object(control, 'api', side_effect=api), \
                 patch.object(control.time, 'time', return_value=now), \
                 patch.object(control, 'interrupt') as stop:
                control.gate(cfg)
                stop.assert_not_called()

    def test_watchdog_interrupts_only_our_active_sessions(self):
        # A missing free route must stop ours without touching unrelated sessions.
        cfg = {'deadline': float('inf'), 'workers': [
            {'session': 'ours', 'path': '/work'}, {'session': 'idle', 'path': '/work'}]}
        with patch.object(control, 'free_route_error', return_value='Route unavailable'), \
             patch.object(control, 'api', return_value={'ours': {}, 'unrelated': {}}), \
             patch.object(control, 'interrupt') as stop:
            control.gate(cfg)
            stop.assert_called_once_with(cfg['workers'][0])

    def test_review_feedback_cannot_bypass_free_price_guard(self):
        # Reviewer instructions never authorize paid fallback when free is missing.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.opencode').mkdir()
            (root / '.opencode/review-feedback.json').write_text(json.dumps({
                'id': 'new-review', 'decision': 'changes_requested'}))
            cfg = {'workers': [{'name': 'qemu', 'path': str(root),
                                 'session': 'ours', 'state': 'awaiting_review'}]}
            with patch.object(control, 'free_route_error', return_value='Route unavailable'), \
                 patch.object(control, 'api', return_value={}) as api, \
                 patch.object(control, 'save'):
                control.tick(cfg)
                api.assert_called_once_with('GET', '/api/session/active')
                self.assertEqual(cfg['inference_hold'], 'Route unavailable')

    def test_review_hold_stops_the_assigned_active_worker(self):
        # A notification saying a decision is needed must not leave work running.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.opencode').mkdir()
            (root / '.opencode/review-feedback.json').write_text(json.dumps({
                'id': 'hold', 'decision': 'hold', 'next_action': 'A decision is needed'}))
            worker = {'name': 'qemu', 'path': str(root), 'session': 'ours', 'state': 'running'}
            with patch.object(control, 'free_route_error', return_value=None), \
                 patch.object(control, 'api', return_value={'ours': {}, 'unrelated': {}}), \
                 patch.object(control, 'interrupt') as interrupt, patch.object(control, 'save'):
                control.tick({'workers': [worker]})
                interrupt.assert_called_once_with(worker)
                self.assertEqual(worker['state'], 'blocked')

    def test_unfinished_generation_cannot_reuse_an_old_completion_note(self):
        # Failure or a watchdog interruption must retry, not accept stale notes.
        for outcome in ('failed', 'interrupted'):
            with self.subTest(outcome=outcome):
                self.check_unfinished_generation(outcome)

    def check_unfinished_generation(self, outcome):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'notes').mkdir()
            (root / 'notes/status.json').write_text('{"status":"ready_for_review"}')
            worker = {'name': 'qemu', 'path': temp, 'session': 'ours', 'state': 'running'}
            def api(method, path):
                return {} if path.endswith('/active') else {'outcome': outcome}
            with patch.object(control, 'free_route_error', return_value=None), \
                 patch.object(control, 'api', side_effect=api), patch.object(control, 'save'), \
                 patch.object(control.time, 'time', return_value=100):
                control.tick({'workers': [worker]})
                self.assertEqual(worker['state'], 'retry')
                self.assertEqual(worker['errors'], 1)
                self.assertGreater(worker['next_run'], 100)
                control.tick({'workers': [worker]})
                self.assertEqual(worker['errors'], 1)
                worker.update(state='running', errors=4)
                control.tick({'workers': [worker]})
                self.assertEqual(worker['state'], 'blocked')
                self.assertEqual(worker['errors'], 5)


if __name__ == '__main__':
    unittest.main()
