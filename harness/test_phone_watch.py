"""Connection/privacy boundaries cannot be tested by the ARM guest."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import control
import notify
import phone_watch


class ConnectionBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []

    def device(self, name, vendor, product):
        path = self.root / name
        path.mkdir()
        (path / 'idVendor').write_text(vendor)
        (path / 'idProduct').write_text(product)

    def test_unrelated_devices_recovery_and_ambiguity_never_query_ios(self):
        def unexpected(args):
            self.fail(f'Unexpected device access: {args[0]}')
        self.device('keyboard', '05ac', '024f')
        self.device('android', '18d1', '4ee7')
        self.assertEqual(phone_watch.observe(self.root, unexpected)['status'], 'no_device')
        self.device('phone', '05ac', '1227')
        self.assertEqual(phone_watch.observe(self.root, unexpected)['status'], 'dfu')
        (self.root / 'phone/idProduct').write_text('1281')
        self.assertEqual(phone_watch.observe(self.root, unexpected)['status'], 'recovery')
        self.device('second', '05ac', '1297')
        self.assertEqual(phone_watch.observe(self.root, unexpected)['status'], 'multiple_devices')

    def test_identification_avoids_pairing_and_exports_only_selected_facts(self):
        self.device('phone', '05ac', '1297')
        udid = 'a' * 40
        facts = {'ProductType': 'iPhone3,1', 'HardwareModel': 'N90AP',
                 'ProductVersion': '7.1.2', 'BuildVersion': '11D257'}
        def read(args):
            self.calls.append(args)
            if args == ['/usr/bin/idevice_id', '-l']:
                return udid
            self.assertEqual(args[:4], ['/usr/bin/ideviceinfo', '-s', '-u', udid])
            self.assertEqual(args[4], '-k')
            return facts[args[5]]
        result = phone_watch.observe(self.root, read)
        self.assertEqual(result['status'], 'identified_n90')
        self.assertEqual(result['identity'], facts)
        self.assertNotIn(udid, json.dumps(result))
        facts['BuildVersion'] = 'error containing a personal device name'
        facts['HardwareModel'] = 'N92AP'
        result = phone_watch.observe(self.root, read)
        self.assertEqual(result['status'], 'other_model')
        self.assertNotIn('BuildVersion', result['identity'])
        facts['HardwareModel'] = ''
        self.assertEqual(phone_watch.observe(self.root, read)['status'], 'identity_unavailable')

    def test_failed_identity_does_not_guess_a_model_or_leak_error_output(self):
        self.device('phone', '05ac', '1297')
        for response in (None, 'unexpected private error', 'a' * 40 + '\n' + 'b' * 40):
            result = phone_watch.observe(self.root, lambda _: response)
            self.assertEqual(result['status'], 'identity_unavailable')
            self.assertEqual(result['identity'], {})

    def test_recovery_identity_requires_pinned_ecid_and_tracks_loader_transition(self):
        # A USB PID alone is not N90 identity; loader IDs lose the ECID but
        # must stay on the identified socket. Neither establishes Linux boot.
        self.device('phone', '05ac', '1281')
        phone = self.root / 'phone'
        (phone / 'serial').write_text('ECID:3039')
        target = {'devpath': str(phone),
                  'ecid_sha256': hashlib.sha256(b'12345').hexdigest()}
        def no_query(_):
            self.fail('Recovery observation must not compete with the USB operator')
        observation = phone_watch.observe(self.root, no_query, target)
        self.assertEqual(observation['identity']['ProductType'], 'iPhone3,1')
        self.assertEqual(observation['status'], 'recovery')
        (phone / 'serial').write_text('ECID:3040')
        self.assertEqual(phone_watch.observe(self.root, no_query, target)['identity'], {})
        (phone / 'idVendor').write_text('0525')
        (phone / 'idProduct').write_text('a4a2')
        observation = phone_watch.observe(self.root, no_query, target)
        self.assertEqual(observation['status'], 'linux_usb')
        self.assertIn('same USB socket', observation['identity_source'])
        self.assertIn('not proof', observation['evidence'])

    def test_observation_resumes_idle_lane_once_but_never_overrides_a_hold(self):
        (self.root / '.opencode').mkdir()
        (self.root / 'notes').mkdir()
        (self.root / 'notes/status.json').write_text('{"status":"ready_for_review"}')
        (self.root / '.opencode/phone-observation.json').write_text(
            '{"status":"identified_n90","event_id":"connected"}')
        w = {'name': 'kernel', 'session': 'ours', 'path': str(self.root),
             'state': 'awaiting_review'}
        api_calls = []
        def api(method, path, *args):
            api_calls.append((method, path))
            return {'outcome': 'succeeded'} if path.endswith('/ours') else {}
        with patch.object(control, 'api', side_effect=api), \
             patch.object(control, 'free_route_error', return_value=None), \
             patch.object(control, 'save'), \
             patch.object(control.shutil, 'disk_usage', return_value=type('Usage', (), {'free': 100 * 1024**3})()):
            control.tick({'workers': [w]})
            self.assertEqual(w['state'], 'running')
            self.assertEqual(w['observation_seen'], 'connected')
            control.tick({'workers': [w]})
            self.assertEqual(w['state'], 'awaiting_review')
            self.assertEqual(sum(p.endswith('/command') for _, p in api_calls), 1)
            (self.root / '.opencode/review-feedback.json').write_text(
                '{"id":"held","decision":"hold","next_action":"Review needed"}')
            w['feedback_seen'] = 'held'
            w['state'] = 'blocked'
            w.pop('observation_seen')
            control.tick({'workers': [w]})
            self.assertEqual(w['state'], 'blocked')
            self.assertEqual(sum(p.endswith('/command') for _, p in api_calls), 1)

    def test_owner_alert_waits_for_persistent_problem_and_normal_arrival_is_quiet(self):
        observation = {'status': 'identity_unavailable',
                       'checked_at': '1970-01-01T00:03:00+00:00',
                       'observed_since': '1970-01-01T00:01:00+00:00'}
        self.assertEqual(notify.phone_events(observation, 100), [])
        self.assertEqual(len(notify.phone_events(observation, 181)), 1)
        observation['status'] = 'identified_n90'
        self.assertEqual(notify.phone_events(observation, 181), [])
        observation['status'] = 'identity_unavailable'
        self.assertEqual(notify.phone_events(observation, 900), [])


if __name__ == '__main__':
    unittest.main()
