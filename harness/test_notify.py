"""User-visible alert contracts; guest boot tests cannot cover Telegram delivery."""
import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import notify
import review


class CriticalAlerts(unittest.TestCase):
    def test_normal_review_queue_is_quiet_but_limits_and_user_decisions_alert(self):
        cfg = {'deadline': 1000, 'workers': [{'name': 'qemu', 'state': 'awaiting_review'}]}
        health = {'review timer': (True, True)}
        self.assertEqual(notify.critical_events(cfg, [], health, 100), [])
        cfg['workers'][0]['state'] = 'limit'
        self.assertEqual(len(notify.critical_events(cfg, [], health, 100)), 1)
        record = {'started': 90, 'reviews': [{'lane': 'kernel', 'decision': 'hold',
                  'attention': 'user', 'user_action': 'Connect the cable when it arrives.'}]}
        self.assertEqual(len(notify.critical_events(cfg, [record], health, 100)), 2)

    def test_sent_incident_is_quiet_until_it_resolves_and_recurs(self):
        calls, state = [], {}
        sender = lambda text: calls.append(text) or '123'
        event = notify.event('stopped', 'Stopped.', 'Repair needed.')
        for when in (1, 2):
            notify.dispatch([event], state, sender, lambda _: None, when)
        self.assertEqual(len(calls), 1)
        notify.dispatch([], state, sender, lambda _: None, 3)
        notify.dispatch([event], state, sender, lambda _: None, 4)
        self.assertEqual(len(calls), 2)

    def test_offline_alert_survives_recovery_and_uncertain_send_has_bounded_retries(self):
        state, calls = {}, []
        event = notify.event('fault', 'Fault.', 'Repair needed.')
        def offline(_):
            raise notify.Offline()
        notify.dispatch([event], state, offline, lambda _: None, 1)
        notify.dispatch([], state, lambda text: calls.append(text) or '42', lambda _: None, 302)
        self.assertEqual(len(calls), 1)
        self.assertIn('no longer active', calls[0])
        def uncertain(text):
            calls.append(text)
            raise TimeoutError()
        state = {}
        for when in (1, 2, 1802, 3603, 6000):
            notify.dispatch([event], state, uncertain, lambda _: None, when)
        self.assertEqual(len(calls), 4)  # one recovered send plus three bounded attempts
        self.assertEqual(state['incidents']['fault']['state'], 'delivery_unknown')

    def test_review_cannot_request_action_without_a_concrete_held_goal(self):
        item = {'lane': 'qemu', 'decision': 'continue', 'findings': [],
                'next_action': 'Continue', 'attention': 'user', 'user_action': 'Do something'}
        with self.assertRaises(ValueError):
            review.validate({'reviews': [item]})
        item.update(decision='hold', user_action='Approve the proposed hardware step.')
        review.validate({'reviews': [item]})

    def test_broken_review_result_is_reported_instead_of_breaking_the_monitor(self):
        # The most important review failure must not crash its own alert reader.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'reviews').mkdir()
            (root / 'reviews/20260101.json').write_text(json.dumps({'id': '20260101',
                'started': 1, 'state': 'failed_or_publication_unknown'}))
            (root / 'reviews/20260101-result.json').write_text('{unfinished')
            with patch.object(notify.control, 'STATE', root):
                records = notify.review_records()
            events = notify.critical_events({'deadline': 1000, 'workers': []}, records, {}, 10)
            self.assertEqual([e['key'] for e in events], ['review-failed'])

    def test_ongoing_run_does_not_report_expiry_but_explicit_deadline_does(self):
        # Continuous operation must neither crash the monitor nor page weekly.
        cfg = {'deadline': None, 'workers': []}
        self.assertEqual(notify.critical_events(cfg, [], {}, 10**10), [])
        cfg['deadline'] = 100
        self.assertEqual(notify.critical_events(cfg, [], {}, 100)[0]['key'], 'run-ended')


if __name__ == '__main__':
    unittest.main()
