"""Loopback-only UI preview. No heater, broker, credentials or device requests."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

root=Path(__file__).resolve().parent
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        path=self.path.split('?',1)[0]
        if path.startswith('/missing/') or path=='/SD':
            self.send_response(302);self.send_header('Location','/');self.end_headers();return
        if path=='/C':
            content="""<h1>Settings</h1><form method='post' action='/CI'><table>
            <tr><td>General</td><td>Write access (level)</td><td><select name='option_34' aria-label='Write access (level)'><option value='0'>Off</option><option value='1'>On (Standard)</option><option value='2'>On (Complete)</option></select></td></tr>
            <tr><td>MQTT</td><td>Broker server</td><td><input name='option_39' aria-label='Broker server' placeholder='hostname:port'></td></tr>
            <tr><td>MQTT</td><td>Password</td><td><input type='password' name='option_41' aria-label='MQTT password' autocomplete='off'></td></tr>
            <tr><td>MQTT</td><td>Publishing</td><td><select name='option_56' aria-label='MQTT publishing'><option value='0'>Off</option><option value='4'>On</option></select></td></tr>
            </table><input type='submit' value='Save settings'></form>"""
        elif path=='/K':
            content='<h1>Parameters</h1><p>No controller is connected to this preview. Actual parameter pages are on the ESP32.</p>'
        elif path=='/':
            content='<h1>Gateway status</h1><p>This is the local preview. No device values or actions are available here.</p><p><a href="http://10.0.10.49/">Open the ESP32 on port 80</a></p>'
        else:
            self.send_error(404);return
        css=(root/'minimal.css').read_text(encoding='utf-8')
        js=(root/'minimal.js').read_text(encoding='utf-8')
        page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="gateway-token" content="preview"><title>BSB-LAN minimal preview</title><style>{css}</style></head><body><nav aria-label="Main"><a id="main_link" href="/">BSB-LAN MQTT</a><a href="/K">Parameters</a><a href="/C">Settings</a></nav><p><strong>Preview only — no heater connection</strong></p><p id="notice" role="status" aria-live="polite"></p><main>{content}</main><footer>BSB-LAN minimal gateway</footer><script>{js}</script></body></html>'''.encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(page)));self.end_headers();self.wfile.write(page)
    def do_POST(self):
        self.send_response(403);self.send_header('Content-Type','text/plain; charset=utf-8');self.end_headers();self.wfile.write(b'Preview only. No operation performed.')

if __name__=='__main__':
    print('Minimal preview: http://127.0.0.1:8765/ (no device operations)',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
