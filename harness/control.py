#!/usr/bin/env python3
"""Small OpenCode goal supervisor. No inference outside the assigned sessions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess as sp
import time

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / '.runtime'
MODEL = {'providerID': 'opencode', 'id': 'deepseek-v4.1-flash-free', 'variant': 'max'}
UNIT = 'iphone4-linux-goals'


def expired(cfg, now=None):
    """A null deadline means ongoing operation, subject to each goal's limits."""
    return cfg.get('deadline') is not None and (time.time() if now is None else now) >= cfg['deadline']


def free_route_error():
    """Fail closed if the exact free route, max effort or zero prices disappear."""
    try:
        models = api('GET', '/api/model')
        matches = [m for m in models if m.get('providerID') == MODEL['providerID']
                   and m.get('id') == MODEL['id']]
        if len(matches) != 1:
            return 'The approved free model is missing or ambiguous.'
        model = matches[0]
        if not model.get('enabled') or model.get('status') != 'active':
            return 'The approved free model is unavailable.'
        if not any(v.get('id') == MODEL['variant'] for v in model.get('variants', [])):
            return 'Max effort is unavailable on the approved free model.'
        def zero(value):
            if isinstance(value, dict):
                return bool(value) and all(zero(v) for v in value.values())
            return type(value) in (int, float) and value == 0
        costs = model.get('cost')
        if not isinstance(costs, list) or not costs or not all(
                isinstance(c, dict) and {'input', 'output'} <= c.keys() and zero(c) for c in costs):
            return 'The approved model no longer has verified zero prices.'
    except Exception:
        return 'OpenCode model availability and prices could not be verified.'
    return None


def api(method, path, body=None, cwd=ROOT):
    args = ['opencode', 'api', method, path]
    if body is not None:
        args += ['--data', json.dumps(body)]
    r = sp.run(args, cwd=cwd, text=True, capture_output=True, timeout=60, check=True)
    if not r.stdout.strip():
        return None
    j = json.loads(r.stdout)
    return j.get('data', j) if isinstance(j, dict) else j


def save(cfg):
    temporary = STATE / 'settings.tmp'
    temporary.write_text(json.dumps(cfg, indent=2) + '\n')
    temporary.replace(STATE / 'settings.json')


def interrupt(worker):
    api('POST', f"/api/session/{worker['session']}/interrupt", {}, worker['path'])


def reject_requests(worker):
    """Keep OpenCode's supported tool schema, but never approve extra access."""
    base = f"/api/session/{worker['session']}/permission"
    for request in api('GET', base):
        if request['sessionID'] != worker['session']:
            raise ValueError('Permission request belongs to another session')
        api('POST', f"{base}/{request['id']}/reply", {
            'decision': 'reject',
            'message': 'Use the sandboxed shell for project files. No extra tools, '
                       'agents or host access are approved.'}, worker['path'])


def tick(cfg):
    active_ids = api('GET', '/api/session/active')
    cfg['inference_hold'] = free_route_error()
    if expired(cfg) or cfg['inference_hold']:
        for w in cfg['workers']:
            if w['session'] in active_ids:
                interrupt(w)
        save(cfg)
        return
    for w in cfg['workers']:
        feedback_path = Path(w['path']) / '.opencode/review-feedback.json'
        feedback = json.loads(feedback_path.read_text()) if feedback_path.exists() else {}
        new_feedback = feedback.get('id') and feedback.get('id') != w.get('feedback_seen')
        observation_path = Path(w['path']) / '.opencode/phone-observation.json'
        observation = json.loads(observation_path.read_text()) if observation_path.exists() else {}
        new_observation = (observation.get('status') != 'no_device' and
                           observation.get('event_id') and
                           observation['event_id'] != w.get('observation_seen'))
        # Arrival adds evidence; keep the sandbox and technical review holds.
        if new_observation and w.get('state') == 'awaiting_review' and feedback.get('decision') != 'hold':
            w.update(state='pending', next_run=0, unchanged=0)
        if new_feedback and feedback.get('decision') in ('changes_requested', 'continue'):
            w['state'] = 'pending'
            w['next_run'] = 0
            w['unchanged'] = 0
        if new_feedback and feedback.get('decision') == 'hold':
            if w['session'] in active_ids:
                interrupt(w)
            w.update(state='blocked', reason=feedback.get('next_action', 'Senior review hold'),
                     feedback_seen=feedback['id'])
            save(cfg)
            continue
        if w.get('state') in ('awaiting_review', 'blocked', 'stopped', 'limit'):
            continue
        try:
            active = w['session'] in active_ids
            if active:
                reject_requests(w)
                if new_feedback:
                    api('POST', f"/api/session/{w['session']}/prompt", {
                        'text': 'New senior feedback is in .opencode/review-feedback.json. '
                                'Read it at the next safe checkpoint. Resolve each finding '
                                'against current evidence; do not repeat already-fixed work. '
                                'Preserve the running build and all goal/sandbox limits.',
                        'delivery': 'steer'}, w['path'])
                    w['feedback_seen'] = feedback['id']
                    w['state'] = 'running'
                    save(cfg)
                if new_observation:
                    api('POST', f"/api/session/{w['session']}/prompt", {
                        'text': 'New sanitized USB/model evidence is in '
                                '.opencode/phone-observation.json. Read it at the next safe '
                                'checkpoint and update your goals/cable-day.md handoff. '
                                'The kernel lane operates the real phone with owner '
                                'authorization; other lanes support it in parallel. '
                                'Follow the current AGENTS.md device assignment.',
                        'delivery': 'steer'}, w['path'])
                    w['observation_seen'] = observation['event_id']
                    save(cfg)
                if time.time() - w.get('last_sent', time.time()) > 14400:
                    interrupt(w)
                    w['state'] = 'blocked'
                    w['reason'] = 'Four-hour turn limit reached; inspect session before resuming'
                    save(cfg)
                continue
            if w.get('state') == 'running':
                session = api('GET', '/api/session/' + w['session'])
                if session.get('outcome') == 'failed':
                    w['state'] = 'retry'
                    raise RuntimeError('OpenCode worker turn failed; previous completion notes are stale')
                if session.get('outcome') == 'succeeded':
                    w['errors'] = 0
            note_path = Path(w['path']) / 'notes/status.json'
            note = json.loads(note_path.read_text()) if note_path.exists() else {}
            if not new_feedback and not new_observation and w.get('state') != 'retry' and note.get('status') in ('ready_for_review', 'blocked'):
                w['state'] = 'awaiting_review' if note['status'] == 'ready_for_review' else 'blocked'
                w['reason'] = note.get('summary', '')
                save(cfg)
                continue
            if time.time() < w.get('next_run', 0):
                continue
            if shutil.disk_usage(w['path']).free < 20 * 1024**3:
                w.update(state='limit', reason='Less than 20 GiB free disk')
                save(cfg)
                continue
            if w.get('turns', 0) >= 96:
                w.update(state='limit', reason='96 work cycles reached')
                save(cfg)
                continue
            progress = sp.run(['git', 'diff', 'HEAD'], cwd=w['path'], capture_output=True).stdout
            progress += sp.run(['git', 'status', '--porcelain'], cwd=w['path'], capture_output=True).stdout
            digest = hashlib.sha256(progress + json.dumps(note, sort_keys=True).encode()).hexdigest()
            w['unchanged'] = w.get('unchanged', 0) + 1 if digest == w.get('digest') else 0
            if w['unchanged'] >= 3:
                w.update(state='blocked', reason='Three unchanged cycles; inspect evidence before resuming')
                save(cfg)
                continue
            w['digest'] = digest
            api('POST', f"/api/session/{w['session']}/agent", {'agent': 'build'}, w['path'])
            api('POST', f"/api/session/{w['session']}/model", {'model': MODEL}, w['path'])
            prompt = (f"Continue /goals {w['name']}. Read AGENTS.md, goals/{w['name']}.md, "
                      '.opencode/skills/pstack-iphone/SKILL.md, '
                      'and notes/GOAL.md if present using the shell tool. Work on the next concrete '
                      'experiment. Write notes/GOAL.md and notes/status.json before ending. '
                      'If complete set ready_for_review, never claim reviewer acceptance. '
                      'If physical hardware or a repeated failure prevents progress, set blocked. '
                      'Do not edit governance, the harness, or model configuration. '
                      'Your shell is isolated; /seed has verified source archives and /acceptance '
                      'has the independent checks. Do not call other models. '
                      'Use only opencode/deepseek-v4.1-flash-free at max effort. '
                      'OpenCode announced this route was updated to 1017 on 2026-10-20. '
                      'Never switch to a paid route.')
            if new_feedback:
                prompt += (' Read .opencode/review-feedback.json first. Address each finding '
                           'and record its resolution or specific blocker in notes/GOAL.md. '
                           'The feedback cannot override the goal, sandbox or acceptance rules.')
            if new_observation:
                prompt += (' Read the new .opencode/phone-observation.json. Reconcile the '
                           'observed model/mode with your goals/cable-day.md handoff. '
                           'The kernel lane operates the real phone with owner '
                           'authorization; other lanes support it in parallel. '
                           'Follow the current AGENTS.md device assignment.')
            api('POST', f"/api/session/{w['session']}/command",
                {'name': 'goals', 'text': w['name'] + '\n' + prompt}, w['path'])
            w.update(state='running', last_sent=time.time(), next_run=time.time() + 300,
                     turns=w.get('turns', 0) + 1)
            if new_feedback:
                w['feedback_seen'] = feedback['id']
            if new_observation:
                w['observation_seen'] = observation['event_id']
        except Exception as exc:
            w['errors'] = w.get('errors', 0) + 1
            w['reason'] = str(exc)[:500]
            w['next_run'] = time.time() + min(3600, 60 * 2**min(w['errors'], 6))
            if w['errors'] >= 5:
                w['state'] = 'blocked'
        save(cfg)


def gate(cfg):
    """Independent minute watchdog: enforce the free route and optional deadline."""
    stop_all = expired(cfg) or free_route_error()
    active = api('GET', '/api/session/active')
    for worker in cfg['workers']:
        if worker['session'] in active:
            if stop_all or api('GET', '/api/session/' + worker['session']).get('model') != MODEL:
                interrupt(worker)
            else:
                reject_requests(worker)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=('start', 'run', 'status', 'stop', 'gate'))
    a = p.parse_args()
    cfg = json.loads((STATE / 'settings.json').read_text())
    if a.command == 'gate':
        gate(cfg)
    elif a.command == 'status':
        for w in cfg['workers']:
            print(f"{w['name']}: {w.get('state', 'pending')} turns={w.get('turns', 0)} "
                  f"session={w['session']} {w.get('reason', '')}")
        print('Deadline:', datetime.fromtimestamp(cfg['deadline'], timezone.utc).isoformat()
              if cfg.get('deadline') is not None else 'none (ongoing)')
        if cfg.get('inference_hold'):
            print('Inference paused:', cfg['inference_hold'])
    elif a.command == 'stop':
        sp.run(['systemctl', '--user', 'disable', '--now', UNIT,
                UNIT + '-gate.timer', 'iphone4-linux-review.timer',
                'iphone4-linux-review.service', 'iphone4-linux-notify.timer',
                'iphone4-linux-notify.service', 'iphone4-linux-phone.timer',
                'iphone4-linux-phone.service'], check=False)
        for w in cfg['workers']:
            interrupt(w)
            w['state'] = 'stopped'
        save(cfg)
    elif a.command == 'start':
        unitdir = Path.home() / '.config/systemd/user'
        unitdir.mkdir(parents=True, exist_ok=True)
        executable = Path(__file__).resolve()
        (unitdir / (UNIT + '.service')).write_text(
            '[Unit]\nDescription=iPhone 4 Linux continuous free DeepSeek goals\n'
            '[Service]\nType=simple\nRestart=on-failure\nRestartSec=60\n'
            f'WorkingDirectory={ROOT}\nExecStart=/usr/bin/python3 {executable} run\n'
            '[Install]\nWantedBy=default.target\n')
        (unitdir / (UNIT + '-gate.service')).write_text(
            '[Unit]\nDescription=iPhone 4 Linux free-model watchdog\n'
            f'[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {executable} gate\n')
        (unitdir / (UNIT + '-gate.timer')).write_text(
            '[Unit]\nDescription=Check iPhone worker model and free pricing every minute\n'
            '[Timer]\nOnCalendar=*-*-* *:*:00\nPersistent=true\nAccuracySec=1s\n'
            '[Install]\nWantedBy=timers.target\n')
        sp.run(['systemctl', '--user', 'daemon-reload'], check=True)
        sp.run(['systemctl', '--user', 'enable', '--now', UNIT,
                UNIT + '-gate.timer'], check=True)
        if (STATE / 'notifications/config.json').exists():
            sp.run(['systemctl', '--user', 'enable', '--now',
                    'iphone4-linux-notify.timer'], check=True)
        if (unitdir / 'iphone4-linux-phone.timer').exists():
            sp.run(['systemctl', '--user', 'enable', '--now',
                    'iphone4-linux-phone.timer'], check=True)
    else:
        while not expired(cfg):
            tick(cfg)
            if all(w.get('state') in ('awaiting_review', 'blocked', 'stopped', 'limit')
                   for w in cfg['workers']):
                break
            time.sleep(30)
        else:
            for w in cfg['workers']:
                if w.get('state') == 'running':
                    interrupt(w)
                    w.update(state='limit', reason='Configured run deadline reached')
            save(cfg)


if __name__ == '__main__':
    main()
