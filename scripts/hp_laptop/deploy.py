"""Push the recurring Polymarket jobs (recorder pull, Elon shadow foretest) to the HP Laptop.

Secrets are read from local stores and sent over ssh stdin; nothing is printed.
Run from the Dell:  python scripts/hp_laptop/deploy.py
"""
import base64
import os
import sys
from pathlib import Path

CC = Path.home() / 'OneDrive/Desktop/Claude Code'
sys.path.insert(0, str(CC / 'Misc/hp-linux-laptop/settings-reference/scripts'))
import ocsudo  # noqa: E402

HERE = Path(__file__).resolve().parent
BOT = HERE.parents[1]
PULL = CC / 'Personal/polymarket-tweet-recorder/pull_and_merge.py'
SHARED_ENV = Path.home() / '.credentials/shared.env'
JAXON_BOT_ENV = CC / 'X Agency/Tools/jaXon Slack Bot/.env'
REMOTE = '/srv/polymarket'
UNITS = '/home/openclaw/.config/systemd/user/'


def env_value(path, key):
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    raise SystemExit('%s not found in %s' % (key, path))


def put(local_bytes, remote_path, mode='600'):
    blob = base64.b64encode(local_bytes).decode()
    script = (
        'mkdir -p "$(dirname %s)"\n'
        "printf '%%s' '%s' | base64 -d > %s\n"
        'chmod %s %s\n'
        'wc -c < %s\n' % (remote_path, blob, remote_path, mode, remote_path, remote_path)
    )
    rc, out = ocsudo.run(script)
    print('put %s rc=%s bytes=%s' % (remote_path, rc, out.strip().splitlines()[-1:]))
    if rc:
        raise SystemExit('put failed')


def env_text():
    rows = [
        '# Polymarket recurring jobs. Deployed from the Dell, do not edit here.',
        'RECORDER_TOKEN=' + env_value(SHARED_ENV, 'RECORDER_TOKEN'),
        'SLACK_BOT_TOKEN=' + env_value(JAXON_BOT_ENV, 'SLACK_BOT_TOKEN'),
        'SLACK_DM_USER=UENMV44H3',
        'GOOGLE_DWD_SUBJECT=' + os.environ['GOOGLE_DWD_SUBJECT'],
        'PYTHONUTF8=1',
        '',
    ]
    return '\n'.join(rows).encode('utf-8')


def service(desc, job):
    return """[Unit]
Description=%s
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/home/openclaw/.polymarket.env
WorkingDirectory=%s/PolyMarket_Bot
Nice=10
ExecStart=%s/venv/bin/python %s/run_job.py %s
""" % (desc, REMOTE, REMOTE, REMOTE, job)


def timer(desc, calendar):
    return """[Unit]
Description=%s

[Timer]
OnCalendar=%s
Persistent=true

[Install]
WantedBy=timers.target
""" % (desc, calendar)


def main():
    rc, out = ocsudo.run(
        'set -e\ncd %s\n[ -x venv/bin/python ] || python3 -m venv venv\n'
        'venv/bin/pip install -q pandas pyarrow numpy google-auth google-api-python-client\n' % REMOTE)
    print('venv rc=%s %s' % (rc, out.strip()[-300:]))
    put((HERE / 'run_job.py').read_bytes(), REMOTE + '/run_job.py', '750')
    put(PULL.read_bytes(), REMOTE + '/polymarket-tweet-recorder/pull_and_merge.py', '640')
    put((BOT / 'scripts/foretest/shadow_foretest.py').read_bytes(),
        REMOTE + '/PolyMarket_Bot/scripts/foretest/shadow_foretest.py', '640')
    put(env_text(), '/home/openclaw/.polymarket.env', '600')
    for name, body in (
            ('polymarket-recorder-pull.service', service('Polymarket recorder pull, main and thin', 'recorder-pull')),
            ('polymarket-recorder-pull.timer', timer('Polymarket recorder pull, daily', '*-*-* 05:00:00')),
            ('polymarket-foretest.service', service('Elon shadow foretest', 'foretest')),
            ('polymarket-foretest.timer', timer('Elon shadow foretest, twice daily', '*-*-* 08,20:00:00'))):
        put(body.encode('utf-8'), UNITS + name, '644')
    rc, out = ocsudo.run(
        'export XDG_RUNTIME_DIR=/run/user/$(id -u)\n'
        'systemctl --user daemon-reload\n'
        'systemctl --user enable --now polymarket-recorder-pull.timer polymarket-foretest.timer\n'
        'systemctl --user list-timers --all --no-pager | grep -i polymarket\n')
    print('timers rc=%s\n%s' % (rc, out))


if __name__ == '__main__':
    main()
