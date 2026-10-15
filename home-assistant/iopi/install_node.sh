#!/bin/sh
set -eu
test "$(id -u)" = 0
stage_dir=${1:?Usage: sudo sh install_node.sh /absolute/path/to/iopi-stage}
case "$stage_dir" in /*) ;; *) echo 'Staging path must be absolute' >&2; exit 1 ;; esac
test -f "$stage_dir/config.json"
test ! -e /etc/iopi/config.json
getent group iopi >/dev/null || groupadd --system iopi
id iopi >/dev/null 2>&1 || useradd --system --gid iopi --groups gpio,video --home-dir /nonexistent --shell /usr/sbin/nologin iopi
install -d -m 755 /opt/iopi
install -d -m 750 -o root -g iopi /etc/iopi
install -m 644 "$stage_dir/iopi.py" "$stage_dir/test_iopi.py" "$stage_dir/config.example.json" /opt/iopi/
install -m 640 -o root -g iopi "$stage_dir/config.json" /etc/iopi/config.json
install -m 640 -o root -g iopi "$stage_dir/mqtt.password" /etc/iopi/mqtt.password
install -m 644 -o root -g iopi "$stage_dir/mqtt-ca.pem" /etc/iopi/mqtt-ca.pem
install -m 644 "$stage_dir/iopi.service" /etc/systemd/system/iopi.service
python3 /opt/iopi/iopi.py --config /etc/iopi/config.json --check
cd /opt/iopi
python3 -m unittest -q test_iopi
systemd-analyze verify /etc/systemd/system/iopi.service
systemctl daemon-reload
systemctl enable --now iopi.service
rm -- "$stage_dir/mqtt.password"
systemctl is-active iopi.service
