"""User-visible alert contracts; guest boot tests cannot cover Telegram delivery."""
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import notify
import review


class CriticalAlerts(unittest.TestCase):
    def test_recovery_report_requires_fresh_usb_observation_and_verified_ssh(self):
        # A successful old probe plus a dead watcher must not send an all-clear.
        # Guest/SSH tests cannot cover this host notification boundary.
        observation = {'status': 'linux_usb', 'checked_at': datetime.fromtimestamp(1000, timezone.utc).isoformat()}
        recovered = {'state': 'recovered', 'outage_since': 'fixture', 'tailnet_same_boot': True}
        self.assertEqual(len(notify.reconnect_events(observation, recovered, 1010)), 1)
        self.assertEqual(notify.reconnect_events(observation, recovered, 1400), [])
        self.assertEqual(notify.reconnect_events({**observation, 'status': 'no_device'}, recovered, 1010), [])
        self.assertEqual(notify.reconnect_events(observation, {**recovered, 'state': 'waiting_ssh'}, 1010), [])

    def test_missing_gateway_catalog_uses_real_delivery_acknowledgement(self):
        # Real regression: Telegram polled and message send worked, but the
        # status catalog was empty. Guest tests cannot exercise this API failure.
        status = {'configOnly': True, 'gatewayAuthUnavailable': False,
                  'error': 'unknown channel: telegram'}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'claw.json').write_text(json.dumps({
                'channels': {'telegram': {'allowFrom': ['123']}}}))
            (root / 'config.json').write_text(json.dumps({
                'openclaw_config': str(root / 'claw.json'), 'target': '123',
                'account': 'test', 'command': '/fixture/openclaw'}))
            for response, accepted in [({'payload': {'messageId': '456'}}, True),
                                       ({'payload': {}}, False)]:
                with self.subTest(response=response), patch.object(notify, 'DATA', root), \
                        patch.object(notify.sp, 'run', side_effect=[
                            subprocess.CompletedProcess([], 0, json.dumps(status)),
                            subprocess.CompletedProcess([], 0, json.dumps(response))
                        ]) as run:
                    if accepted:
                        self.assertEqual(notify.send('Fixture alert'), '456')
                    else:
                        with self.assertRaises(ValueError):
                            notify.send('Fixture alert')
                    self.assertEqual(run.call_args.args[0][1:3], ['message', 'send'])

    def test_known_disconnected_account_still_queues_without_sending(self):
        # Catalog fallback must not turn a confirmed outage into send retries.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'claw.json').write_text(json.dumps({
                'channels': {'telegram': {'allowFrom': ['123']}}}))
            (root / 'config.json').write_text(json.dumps({
                'openclaw_config': str(root / 'claw.json'), 'target': '123',
                'account': 'test', 'command': '/fixture/openclaw'}))
            status = {'channelAccounts': {'telegram': [
                {'accountId': 'test', 'connected': False, 'probe': {'ok': False}}]}}
            with patch.object(notify, 'DATA', root), patch.object(
                    notify.sp, 'run', return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps(status))) as run:
                with self.assertRaises(notify.Offline):
                    notify.send('Fixture alert')
                self.assertEqual(run.call_count, 1)

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
