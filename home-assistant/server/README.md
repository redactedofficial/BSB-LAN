# Server integration for the original or compact firmware

These helpers accompany the BMS example at `10.0.10.29`, which already runs
Home Assistant, Mosquitto and the RMS bridge. They are not generic first-install
scripts for an unrelated broker. Review the existing account names, paths and
listener bindings before deployment. They never send boiler or relay commands.

`configure_mqtt.py` backs up the current ACL, retains the authenticated loopback
listener and adds a separately authenticated TLS listener on port 8883. It
generates a device identity scoped to BSB-LAN topics and discovery. Private
credentials and the CA key stay in a root-only server archive; configured
firmware binaries and credential files must remain outside Git. Add the public
CA certificate to the ESP32's trust bundle while retaining its existing roots.
The BSB communication and MQTT implementation need no changes.

`verify_mqtt.py` checks TLS authentication, Home Assistant receipt of a
non-retained diagnostic message, and denial of unrelated RMS/discovery topics.

`discovery_compat.py` adapts two stock discovery cases for Home Assistant:

- Microamp sensors retain their values and `µA` unit, without the unsupported
  `current` device class.
- Missing numeric readings such as `---` become `unknown`, never zero.

`install_discovery_compat.py` creates an unprivileged systemd service with a
separate discovery-only MQTT identity. It can only read/write the BSB-LAN sensor
discovery namespace. It cannot publish boiler or rack commands. The adaptation
is idempotent; writable control definitions remain the original firmware's.

Three targeted compatibility tests passed. Live validation on Debian 13,
Mosquitto 2.0.21 and Home Assistant 2026.10 confirmed the ESP32's verified TLS
connection and live setpoint/temperature readings after reconnecting the boiler.
No boiler parameter writes were used for validation. The original firmware
deployment used Frederik's exact private parameter header; the compact branch
remains available as an alternative application.

For rollback, preserve current settings, stop/disable the compatibility service,
move the two added listener configuration files out of `conf.d`, restore the
backed-up ACL where no later changes conflict, and restart Mosquitto. Do not run
the initial RMS deployment script over an existing installation.
