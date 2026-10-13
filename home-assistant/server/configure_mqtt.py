"""Run as root on the BMS host; preserves the existing loopback broker."""
from pathlib import Path
import grp
import json
import os
import secrets
import shutil
import subprocess
import time

BASE = Path('/etc/mosquitto')
ADMIN = BASE / 'bsblan-admin'
CERTS = BASE / 'certs/bsblan'
BACKUP = Path('/opt/bms/backups/bsblan-mqtt-20261013')
USERNAME = 'bsblan_esp'


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root is required for broker configuration.')
    if ADMIN.exists() or BACKUP.exists():
        raise SystemExit('Existing integration or backup found; inspect it before rerunning.')
    original_acl = (BASE / 'rms-acl').read_text()
    assert original_acl.count('user homeassistant_rms\n') == 1
    assert [line for line in original_acl.splitlines() if line.startswith('user ')][-1] == 'user homeassistant_rms'
    assert 'bsblan_esp' not in original_acl
    assert (BASE / 'conf.d/rms.conf').read_text().startswith('listener 1883 127.0.0.1\n')
    BACKUP.mkdir(parents=True, mode=0o700)
    shutil.copy2(BASE / 'rms-acl', BACKUP / 'rms-acl')
    shutil.copy2(BASE / 'conf.d/rms.conf', BACKUP / 'rms.conf')
    ADMIN.mkdir(mode=0o700)
    CERTS.mkdir(parents=True, mode=0o750)
    gid = grp.getgrnam('mosquitto').gr_gid
    os.chown(CERTS, 0, gid)
    password = secrets.token_urlsafe(32)
    credentials = {'broker': '10.0.10.29:8883', 'username': USERNAME,
                   'password': password, 'topic_prefix': 'BSB-LAN',
                   'device_id': 'BSB-LAN'}
    (ADMIN / 'credentials.json').write_text(json.dumps(credentials, indent=2) + '\n')
    os.chmod(ADMIN / 'credentials.json', 0o600)
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256',
        '-days', '3650', '-keyout', str(ADMIN / 'ca.key'), '-out', str(ADMIN / 'ca.pem'),
        '-subj', '/CN=BMS BSB-LAN MQTT CA',
        '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
        '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    os.chmod(ADMIN / 'ca.key', 0o600)
    run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-sha256',
        '-keyout', str(CERTS / 'server.key'), '-out', str(ADMIN / 'server.csr'),
        '-subj', '/CN=10.0.10.29')
    ext = ADMIN / 'server.ext'
    ext.write_text('basicConstraints=critical,CA:FALSE\n'
                   'keyUsage=critical,digitalSignature,keyEncipherment\n'
                   'extendedKeyUsage=serverAuth\n'
                   'subjectAltName=IP:10.0.10.29,DNS:10.0.10.29\n')
    run('openssl', 'x509', '-req', '-sha256', '-days', '825',
        '-in', str(ADMIN / 'server.csr'), '-CA', str(ADMIN / 'ca.pem'),
        '-CAkey', str(ADMIN / 'ca.key'), '-CAcreateserial',
        '-extfile', str(ext), '-out', str(CERTS / 'server.pem'))
    run('openssl', 'verify', '-CAfile', str(ADMIN / 'ca.pem'), str(CERTS / 'server.pem'))
    for name in ('server.key', 'server.pem'):
        os.chmod(CERTS / name, 0o640)
        os.chown(CERTS / name, 0, gid)
    passwords = BASE / 'bsblan-passwords'
    passwords.write_text(f'{USERNAME}:{password}\n')
    os.chmod(passwords, 0o600)
    run('mosquitto_passwd', '-U', str(passwords))
    os.chmod(passwords, 0o640)
    os.chown(passwords, 0, gid)
    acl = BASE / 'bsblan-acl'
    acl.write_text(f'user {USERNAME}\n'
                   'topic readwrite BSB-LAN/#\n'
                   'topic write homeassistant/+/BSB-LAN/#\n'
                   'topic read homeassistant/status\n')
    os.chmod(acl, 0o640)
    os.chown(acl, 0, gid)
    auth_config = BASE / 'conf.d/00-bsblan-auth.conf'
    listener_config = BASE / 'conf.d/z-bsblan-tls.conf'
    tls = ('listener 8883 10.0.10.29\n'
           'allow_anonymous false\n'
           'password_file /etc/mosquitto/bsblan-passwords\n'
           'acl_file /etc/mosquitto/bsblan-acl\n'
           'certfile /etc/mosquitto/certs/bsblan/server.pem\n'
           'keyfile /etc/mosquitto/certs/bsblan/server.key\n'
           'tls_version tlsv1.2\n')
    test = ADMIN / 'validate.conf'
    test.write_text('per_listener_settings true\n' +
                    (BASE / 'conf.d/rms.conf').read_text().replace('1883 127.0.0.1', '18884 127.0.0.1') +
                    tls.replace('8883 10.0.10.29', '18885 127.0.0.1') +
                    'log_dest stdout\n')
    proc = subprocess.Popen(['mosquitto', '-c', str(test)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        time.sleep(1)
        if proc.poll() is not None:
            raise RuntimeError('Broker validation failed before applying listener settings.')
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.communicate(timeout=5)
    # The HA user keeps its current RMS ACL entries and gains only BSB-LAN topics.
    (BASE / 'rms-acl').write_text(original_acl + '\n# BSB-LAN integration\ntopic readwrite BSB-LAN/#\n')
    auth_config.write_text('per_listener_settings true\n')
    listener_config.write_text(tls)
    try:
        run('systemctl', 'restart', 'mosquitto')
        run('systemctl', 'is-active', '--quiet', 'mosquitto')
    except Exception:
        shutil.copy2(BACKUP / 'rms-acl', BASE / 'rms-acl')
        auth_config.rename(ADMIN / 'auth.failed.conf')
        listener_config.rename(ADMIN / 'tls.failed.conf')
        run('systemctl', 'restart', 'mosquitto')
        raise
    print('TLS listener configured on 10.0.10.29:8883; existing loopback listener preserved.')
    print('ESP32 credentials saved privately; no hardware commands were sent.')


if __name__ == '__main__':
    main()
