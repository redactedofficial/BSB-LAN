"""Install a loopback-only, discovery-only service identity without changing ESP code."""
from pathlib import Path
import json
import os
import secrets
import shutil
import subprocess

base = Path('/etc/mosquitto')
archive = base / 'bsblan-admin'
username = 'bsblan_discovery'
credentials_path = archive / 'discovery-credentials.json'
if credentials_path.exists():
    raise SystemExit('Existing discovery credentials; inspect rather than overwrite.')
password = secrets.token_urlsafe(32)
subprocess.run(['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin',
                'bsblan-discovery'], check=True)
credentials_path.write_text(json.dumps({'username': username, 'password': password}) + '\n')
os.chmod(credentials_path, 0o600)
temp_passwords = archive / 'discovery-password.hash'
temp_passwords.write_text(f'{username}:{password}\n')
os.chmod(temp_passwords, 0o600)
subprocess.run(['mosquitto_passwd', '-U', str(temp_passwords)], check=True)
passwords = base / 'rms-passwords'
acl = base / 'rms-acl'
shutil.copy2(passwords, archive / 'rms-passwords.before-discovery')
shutil.copy2(acl, archive / 'rms-acl.before-discovery')
assert username not in passwords.read_text()
with passwords.open('a') as f:
    f.write(temp_passwords.read_text())
with acl.open('a') as f:
    f.write(f'\nuser {username}\ntopic readwrite homeassistant/sensor/BSB-LAN/+/config\n')
service = Path('/etc/systemd/system/bsblan-discovery.service')
service.write_text('''[Unit]
Description=BSB-LAN Home Assistant sensor discovery compatibility
After=mosquitto.service network-online.target
Wants=mosquitto.service

[Service]
User=bsblan-discovery
Group=bsblan-discovery
LoadCredential=mqtt.json:/etc/mosquitto/bsblan-admin/discovery-credentials.json
ExecStart=/opt/rms/.venv/bin/python /opt/bms/bsblan-discovery.py
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
''')
subprocess.run(['systemctl', 'reload', 'mosquitto'], check=True)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'enable', '--now', 'bsblan-discovery'], check=True)
print('Discovery-only compatibility service installed; no control-topic permissions.')
