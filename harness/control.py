#!/usr/bin/env python3
"""Small OpenCode goal supervisor. No inference outside the assigned sessions."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import subprocess as sp
import time

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / '.runtime'
MODEL = {'providerID': 'deepseek', 'id': 'deepseek-flash', 'variant': 'max'}
UNIT = 'iphone4-linux-goals'


def off_peak(now=None):
    """Official UTC schedule; conservatively skip holiday exceptions.

    Five-minute buffer allows in-flight generations to be interrupted before
    peak billing starts. Weekends use UTC, not the laptop's timezone.
    """
    now = now or datetime.now(timezone.utc)
    for dt in (now, now + timedelta(minutes=5)):
        if dt.weekday() < 5 and (1 <= dt.hour < 4 or 6 <= dt.hour < 10):
            return False
    return True


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


def tick(cfg):
    active_ids = api('GET', '/api/session/active')
    for w in cfg['workers']:
        feedback_path = Path(w['path']) / '.opencode/review-feedback.json'
        feedback = json.loads(feedback_path.read_text()) if feedback_path.exists() else {}
        new_feedback = feedback.get('id') and feedback.get('id') != w.get('feedback_seen')
        if new_feedback and feedback.get('decision') in ('changes_requested', 'continue'):
            w['state'] = 'pending'
            w['next_run'] = 0
            w['unchanged'] = 0
        if w.get('state') in ('awaiting_review', 'blocked', 'stopped', 'limit'):
            continue
        try:
            active = w['session'] in active_ids
            if not off_peak():
                if active:
                    interrupt(w)
                w['state'] = 'waiting_off_peak'
                save(cfg)
                continue
            if active:
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
                if time.time() - w.get('last_sent', time.time()) > 14400:
                    interrupt(w)
                    w['state'] = 'blocked'
                    w['reason'] = 'Four-hour turn limit reached; inspect session before resuming'
                    save(cfg)
                continue
            note_path = Path(w['path']) / 'notes/status.json'
            note = json.loads(note_path.read_text()) if note_path.exists() else {}
            if not new_feedback and note.get('status') in ('ready_for_review', 'blocked'):
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
                      'The official deepseek/deepseek-flash route is DeepSeek-V4.1-Flash-1017.')
            if new_feedback:
                prompt += (' Read .opencode/review-feedback.json first. Address each finding '
                           'and record its resolution or specific blocker in notes/GOAL.md. '
                           'The feedback cannot override the goal, sandbox or acceptance rules.')
            api('POST', f"/api/session/{w['session']}/command",
                {'name': 'goals', 'text': w['name'] + '\n' + prompt}, w['path'])
            w.update(state='running', last_sent=time.time(), next_run=time.time() + 300,
                     turns=w.get('turns', 0) + 1, errors=0)
            if new_feedback:
                w['feedback_seen'] = feedback['id']
        except Exception as exc:
            w['errors'] = w.get('errors', 0) + 1
            w['reason'] = str(exc)[:500]
            w['next_run'] = time.time() + min(3600, 60 * 2**min(w['errors'], 6))
            if w['errors'] >= 5:
                w['state'] = 'blocked'
        save(cfg)


def gate(cfg):
    """Independent minute watchdog: stop inference outside the paid window."""
    if off_peak() and time.time() < cfg['deadline']:
        return
    active = api('GET', '/api/session/active')
    for worker in cfg['workers']:
        if worker['session'] in active:
            interrupt(worker)


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
        print('Deadline:', datetime.fromtimestamp(cfg['deadline'], timezone.utc).isoformat())
    elif a.command == 'stop':
        sp.run(['systemctl', '--user', 'disable', '--now', UNIT,
                UNIT + '-gate.timer', 'iphone4-linux-review.timer',
                'iphone4-linux-review.service'], check=False)
        for w in cfg['workers']:
            interrupt(w)
            w['state'] = 'stopped'
        save(cfg)
    elif a.command == 'start':
        unitdir = Path.home() / '.config/systemd/user'
        unitdir.mkdir(parents=True, exist_ok=True)
        executable = Path(__file__).resolve()
        (unitdir / (UNIT + '.service')).write_text(
            '[Unit]\nDescription=iPhone 4 Linux off-peak DeepSeek goals\n'
            '[Service]\nType=simple\nRestart=on-failure\nRestartSec=60\n'
            f'WorkingDirectory={ROOT}\nExecStart=/usr/bin/python3 {executable} run\n'
            '[Install]\nWantedBy=default.target\n')
        (unitdir / (UNIT + '-gate.service')).write_text(
            '[Unit]\nDescription=iPhone 4 Linux off-peak cutoff watchdog\n'
            f'[Service]\nType=oneshot\nExecStart=/usr/bin/python3 {executable} gate\n')
        (unitdir / (UNIT + '-gate.timer')).write_text(
            '[Unit]\nDescription=Check iPhone worker billing window every minute\n'
            '[Timer]\nOnCalendar=*-*-* *:*:00\nPersistent=true\nAccuracySec=1s\n'
            '[Install]\nWantedBy=timers.target\n')
        sp.run(['systemctl', '--user', 'daemon-reload'], check=True)
        sp.run(['systemctl', '--user', 'enable', '--now', UNIT,
                UNIT + '-gate.timer'], check=True)
    else:
        while time.time() < cfg['deadline']:
            tick(cfg)
            if all(w.get('state') in ('awaiting_review', 'blocked', 'stopped', 'limit')
                   for w in cfg['workers']):
                break
            time.sleep(30)
        else:
            for w in cfg['workers']:
                if w.get('state') == 'running':
                    interrupt(w)
                    w.update(state='limit', reason='Seven-day run window ended')
            save(cfg)


if __name__ == '__main__':
    main()
