#!/usr/bin/env python3
"""Quiet critical-event monitor; send fixed reports through the existing Soyclaw bot."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess as sp
import time

import control
import review

DATA = control.STATE / 'notifications'
LINK = 'https://github.com/kpoxo6op/iphone4-linux'
ISSUES = {'qemu': 1, 'kernel': 2, 'drivers': 3}


class Offline(Exception):
    """No message was attempted; keep the alert queued until Telegram recovers."""


def event(key, text, action, lane=None):
    url = LINK + (f'/issues/{ISSUES[lane]}' if lane in ISSUES else '/issues')
    return {'key': key, 'message': f'iPhone Linux\n\n{text}\n\n{action}\n{url}'}


def review_records():
    records = []
    for path in (control.STATE / 'reviews').glob('20*.json'):
        if path.stem.endswith(('-packet', '-result')):
            continue
        try:
            record = json.loads(path.read_text())
            resultfile = path.with_name(path.stem + '-result.json')
            if resultfile.exists():
                result = json.loads(resultfile.read_text())
                review.validate(result)
                record['reviews'] = result['reviews']
        except (ValueError, TypeError, KeyError):
            record = {'id': path.stem, 'started': path.stat().st_mtime,
                      'state': 'failed_or_publication_unknown'}
        records.append(record)
    return records


def critical_events(cfg, records, health, now):
    events = []
    if control.expired(cfg, now):
        return [event('run-ended', 'The scheduled run window has ended.',
                      'A new run window is needed to continue.')]
    for worker in cfg['workers']:
        lane = worker['name']
        if worker.get('state') == 'limit' or worker.get('errors', 0) >= 5:
            events.append(event('worker-limit:' + lane,
                                f'The {lane} worker stopped after exhausting a resource or retry limit.',
                                'The project needs a maintainer repair before this lane can continue.', lane))
    if records:
        latest = max(records, key=lambda r: r['started'])
        if latest.get('state') == 'failed_or_publication_unknown':
            events.append(event('review-failed', 'The automatic senior review failed or its GitHub post could not be confirmed.',
                                'Some corrections may not have reached the workers. A maintainer needs to repair the review loop.'))
        for item in latest.get('reviews', []):
            if item.get('attention') == 'user' and item.get('decision') == 'hold':
                action = item.get('user_action', '')
                if (item.get('lane') in ISSUES and isinstance(action, str) and
                        action.strip() and len(action) <= 400 and not review.SENSITIVE.search(action)):
                    key = 'user:' + item['lane'] + ':' + hashlib.sha256(action.encode()).hexdigest()[:12]
                    events.append(event(key, f'The {item["lane"]} goal needs your decision.', action, item['lane']))
    for name, (enabled, active) in health.items():
        if not active:
            events.append(event('service:' + name, f'The project’s {name} is not running.',
                                'A maintainer needs to restore it. The alert monitor will keep checking.'))
    return events


def dispatch(events, state, sender, save, now):
    """Deduplicate delivered incidents and retain an offline delivery queue."""
    incidents = state.setdefault('incidents', {})
    current = {e['key'] for e in events}
    for key, old in incidents.items():
        if key not in current:
            old['open'] = False
    for item in events:
        prior = incidents.get(item['key'])
        if prior and prior.get('open'):
            continue
        incidents[item['key']] = {'open': True, 'state': 'queued', 'time': now,
                                  'message': item['message'], 'attempts': 0}
    for key, record in incidents.items():
        if record['state'] not in ('queued', 'retry') or now < record.get('next_try', 0):
            continue
        record['state'] = 'sending'
        save(state)
        try:
            message = record['message']
            if not record['open']:
                message += '\n\nUpdate: this condition is no longer active.'
            alert_id = hashlib.sha256((key + str(record['time'])).encode()).hexdigest()[:8]
            record['message_id'] = sender(message + '\nAlert ' + alert_id)
            record['state'] = 'delivered'
        except Offline:
            record.update(state='queued', next_try=now + 300)
        except Exception:
            # A lost acknowledgment can duplicate a retry. Keep the same alert
            # ID, back off, and cap retries rather than silently dropping it.
            record['attempts'] += 1
            record.update(state='retry' if record['attempts'] < 3 else 'delivery_unknown',
                          next_try=now + 1800)
        save(state)
    save(state)


def send(text):
    config = json.loads((DATA / 'config.json').read_text())
    # Only Boris's existing private allowlisted chat; workers cannot set a target.
    claw = json.loads(Path(config['openclaw_config']).read_text())
    allowed = claw['channels']['telegram'].get('allowFrom', [])
    if config['target'] not in allowed or not str(config['target']).isdigit():
        raise ValueError('Notification target is no longer allowlisted')
    try:
        status = sp.run([config['command'], 'channels', 'status', '--channel', 'telegram',
                         '--probe', '--json'], capture_output=True, text=True,
                        timeout=25, check=True)
        channels = json.loads(status.stdout[status.stdout.index('{'):])
        accounts = channels.get('channelAccounts', {}).get('telegram', [])
        if not any(a.get('accountId') == config['account'] and a.get('connected')
                   and a.get('probe', {}).get('ok') for a in accounts):
            raise Offline()
    except (sp.SubprocessError, ValueError, OSError) as exc:
        raise Offline() from exc
    response = sp.run([config['command'], 'message', 'send', '--channel', 'telegram',
                       '--account', config['account'], '--target', config['target'],
                       '--message', text, '--json'], capture_output=True, text=True,
                      timeout=45, check=True)
    result = json.loads(response.stdout[response.stdout.index('{'):])
    payload = result.get('payload', {})
    message_id = result.get('messageId') or payload.get('messageId')
    if result.get('dryRun') or not message_id:
        raise ValueError('Soyclaw did not return a delivery identifier')
    return str(message_id)


def unit_health(unit):
    enabled = sp.run(['systemctl', '--user', 'is-enabled', unit], capture_output=True).returncode == 0
    active = sp.run(['systemctl', '--user', 'is-active', unit], capture_output=True).returncode == 0
    return enabled, active


def check(test=False):
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (DATA / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        statefile = DATA / 'state.json'
        state = json.loads(statefile.read_text()) if statefile.exists() else {}
        for record in state.get('incidents', {}).values():
            if record['state'] == 'sending':
                record['attempts'] = record.get('attempts', 0) + 1
                record.update(state='retry' if record['attempts'] < 3 else 'delivery_unknown',
                              next_try=time.time() + 1800)
        save = lambda value: review.atomic(statefile, value)
        cfg = json.loads((control.STATE / 'settings.json').read_text())
        # An explicit project stop is intentional and must not page Boris.
        if not unit_health(control.UNIT + '.service')[0]:
            return
        now = time.time()
        records = review_records()
        health = {'free-model watchdog': unit_health(control.UNIT + '-gate.timer'),
                  'review timer': unit_health('iphone4-linux-review.timer')}
        events = critical_events(cfg, records, health, now)
        expected = any(w.get('state') not in ('awaiting_review', 'blocked', 'stopped', 'limit')
                       for w in cfg['workers'])
        if expected and not unit_health(control.UNIT + '.service')[1]:
            events.append(event('supervisor-down', 'The worker supervisor has stopped unexpectedly.',
                                'Automatic work needs a maintainer repair.'))
        attemptsfile = control.STATE / 'reviews/attempts.json'
        attempts = json.loads(attemptsfile.read_text()) if attemptsfile.exists() else []
        if attempts:
            last = attempts[-1]
            if now - last['started'] > 1800 and not any(r['id'] == last['id'] for r in records):
                events.append(event('review-lost', 'The last senior review never recorded a result.',
                                    'The review process needs a maintainer check before it is retried.'))
        # Queued reviews are quiet. A paid/unverifiable route must pause and alert.
        try:
            active = control.api('GET', '/api/session/active')
            route_error = control.free_route_error()
            if route_error:
                events.append(event('free-model-unavailable', route_error,
                                    'Workers are paused. The maintainer must restore the approved free route; there is no paid fallback.'))
            for worker in cfg['workers']:
                if worker['session'] not in active:
                    continue
                session = control.api('GET', '/api/session/' + worker['session'])
                if session.get('model') != control.MODEL:
                    control.interrupt(worker)
                    events.append(event('model:' + worker['name'], 'A worker selected an unapproved model or effort. It was interrupted.',
                                        'The maintainer must restore free DeepSeek 1017 at max effort.', worker['name']))
                if route_error or control.expired(cfg, now):
                    control.interrupt(worker)
                    if control.expired(cfg, now):
                        events.append(event('billing:' + worker['name'], 'A worker was still active past the configured deadline. It was interrupted.',
                                            'The run controls need a maintainer check.', worker['name']))
            state['api_failures'] = 0
        except Exception:
            state['api_failures'] = state.get('api_failures', 0) + 1
            if state['api_failures'] >= 3:
                events.append(event('opencode-unreachable', 'OpenCode could not be checked on three consecutive attempts.',
                                    'Worker status and cost enforcement need a maintainer check.'))
        if test:
            events.append(event('setup-test', 'Critical alerts are connected through Soyclaw. This is the one-off delivery test.',
                                'Nothing needs your attention. Routine builds and reviews will stay quiet.'))
        state['last_checked'] = now
        dispatch(events, state, send, save, now)
        print(json.dumps({'checked': True, 'critical_events': len(events),
                          'delivery_unknown': sum(i.get('open') and i['state'] == 'delivery_unknown'
                                                  for i in state['incidents'].values())}))


def install():
    units = Path.home() / '.config/systemd/user'
    (units / 'iphone4-linux-notify.service').write_text(
        '[Unit]\nDescription=Critical iPhone Linux alerts through Soyclaw\n'
        '[Service]\nType=oneshot\n'
        f'WorkingDirectory={control.ROOT}\nExecStart=/usr/bin/python3 {Path(__file__).resolve()} check\n'
        'TimeoutStartSec=5min\nMemoryMax=1G\nCPUQuota=100%\n')
    (units / 'iphone4-linux-notify.timer').write_text(
        '[Unit]\nDescription=Check critical iPhone Linux events every five minutes\n'
        '[Timer]\nOnCalendar=*-*-* *:00/5:00\nPersistent=true\nAccuracySec=10s\n'
        '[Install]\nWantedBy=timers.target\n')
    sp.run(['systemctl', '--user', 'daemon-reload'], check=True)
    sp.run(['systemctl', '--user', 'enable', '--now', 'iphone4-linux-notify.timer'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('check', 'test', 'install', 'status'))
    command = parser.parse_args().command
    if command == 'install':
        install()
    elif command == 'status':
        path = DATA / 'state.json'
        print(path.read_text() if path.exists() else 'Not checked yet')
    else:
        check(test=command == 'test')
