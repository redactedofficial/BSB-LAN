"""Run as root on BMS: add one scoped identity, preserve existing listener/users."""
import grp
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def atomic(path, content, gid):
    temporary = path.with_name(path.name + '.iopi-new')
    temporary.write_text(content, encoding='utf8')
    os.chmod(temporary, 0o640)
    os.chown(temporary, 0, gid)
    os.replace(temporary, path)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run on BMS as root')
    credential_file = Path('/root/iopi-credential.json')
    credential = json.loads(credential_file.read_text())
    base = Path('/etc/mosquitto')
    paths = {name: base / name for name in ('bsblan-passwords', 'bsblan-acl', 'rms-acl')}
    original = {name: path.read_text() for name, path in paths.items()}
    if 'user iopi_node\n' in original['bsblan-acl']:
        raise SystemExit('IOPI broker identity already exists; preserve and inspect')
    if credential['username'] != 'iopi_node' or len(credential['password']) < 32:
        raise SystemExit('Invalid credential metadata')
    backup = Path('/opt/bms/backups') / time.strftime('iopi-mqtt-%Y%m%d-%H%M%S', time.gmtime())
    backup.mkdir(mode=0o700)
    for name, path in paths.items():
        shutil.copy2(path, backup / name)
    gid = grp.getgrnam('mosquitto').gr_gid
    with tempfile.TemporaryDirectory(prefix='iopi-password-', dir='/root') as directory:
        isolated = Path(directory) / 'passwords'
        isolated.write_text(f'iopi_node:{credential["password"]}\n')
        os.chmod(isolated, 0o600)
        subprocess.run(['mosquitto_passwd', '-U', str(isolated)], check=True, capture_output=True)
        hashed = isolated.read_text()
    updated = dict(original)
    updated['bsblan-passwords'] = original['bsblan-passwords'].rstrip() + '\n' + hashed
    node_acl = ['user iopi_node', 'topic write iopi/bmsiopi/#', 'topic read homeassistant/status']
    for component in ('sensor', 'switch', 'binary_sensor', 'select', 'number'):
        node_acl.append(f'topic write homeassistant/{component}/bmsiopi/#')
    for rid in range(1, 9):
        node_acl.append(f'topic read iopi/bmsiopi/relay_{rid}/set')
    node_acl += ['topic read iopi/bmsiopi/heating/mode/set', 'topic read iopi/bmsiopi/heating/cutoff/set',
                 'topic read iopi/bmsiopi/heating/policy/set', 'topic read iopi/bmsiopi/heating/pump_override/set']
    for category, parameter in [(36, 8314), (31, 6700), (37, 8830)]:
        node_acl += [f'topic read BSB-LAN/0/{category}/{parameter}/status',
                     f'topic write BSB-LAN/0/{category}/{parameter}/poll']
    updated['bsblan-acl'] += '\n# IOPI controller\n' + '\n'.join(node_acl) + '\n'
    lines = original['rms-acl'].splitlines(keepends=True)
    start = lines.index('user homeassistant_rms\n')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('user ')), len(lines))
    ha_acl = ['\n# IOPI integration', 'topic read iopi/bmsiopi/#']
    ha_acl += [f'topic write iopi/bmsiopi/relay_{rid}/set' for rid in range(1, 9)]
    ha_acl += ['topic write iopi/bmsiopi/heating/mode/set', 'topic write iopi/bmsiopi/heating/cutoff/set',
               'topic write iopi/bmsiopi/heating/policy/set', 'topic write iopi/bmsiopi/heating/pump_override/set']
    updated['rms-acl'] = ''.join(lines[:end]) + '\n'.join(ha_acl) + '\n\n' + ''.join(lines[end:])
    try:
        for name, path in paths.items():
            atomic(path, updated[name], gid)
        subprocess.run(['systemctl', 'reload', 'mosquitto'], check=True, capture_output=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'mosquitto'], check=True)
    except Exception:
        for name, path in paths.items():
            atomic(path, original[name], gid)
        subprocess.run(['systemctl', 'reload', 'mosquitto'], check=True)
        raise
    credential_file.unlink()
    print('Scoped IOPI MQTT identity installed; existing broker preserved.')
    print('Protected broker backup:', backup)


if __name__ == '__main__':
    main()
