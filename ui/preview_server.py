"""Loopback-only UI preview with explicitly labelled sample data; never talks to a boiler."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
VALUES = {'8310':('42.6','°C'),'8314':('36.2','°C'),'8326':('22','%'),
          '8327':('1.4','bar'),'8700':('---','°C'),'8740':('21.4','°C'),'8830':('48.0','°C')}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        path = self.path.split('?',1)[0]
        prefix = '/basic/' if path.startswith('/basic/') else '/offline/' if path.startswith('/offline/') else '/locked/' if path.startswith('/locked/') else '/missing/' if path.startswith('/missing/') else '/'
        command = path[len(prefix):]
        if command == 'SD/status':
            return self.respond(json.dumps({'mounted':prefix != '/missing/','busy':prefix == '/locked/','selected':True,'authorized':True,'logging':prefix == '/locked/','interval':300,'token':'preview-only','total':8000000000,'used':12000000,'files':[{'name':'datalog.txt','size':42000}],'truncated':False}),'application/json')
        if command == 'JI':
            if prefix == '/offline/':
                self.send_response(503);self.end_headers();return
            return self.respond(json.dumps({'bus':'BSB','busdest':0,'buswritable':0,
                'busdevices':[{'dev_id':0,'dev_fam':123,'dev_name':'Baxi Luna Platinum+ · Siemens LMS15'}]}),'application/json')
        if command.startswith('JQ='):
            ids = command[3:].split(',')
            data = {i:{'error':0,'value':VALUES[i][0],'unit':VALUES[i][1]} for i in ids if i in VALUES}
            return self.respond(json.dumps(data),'application/json')
        supported = '8700' if prefix == '/basic/' else ','.join(VALUES)
        links = ''.join(f'<a href="{prefix}{target}">{label}</a>' for target,label in [('','Overview'),('K','Heater functions'),('C','Settings'),('SD','SD card'),('K6','Sensors'),('Q','Device-specific parameter list')])
        content = '<p>BSB-LAN, Version 5.1.25</p><p>Readings and configuration for the local heating controller.</p>'
        if command == 'C':
            content = '''<form novalidate><table><tr><td>General</td><td>Read config from EEPROM</td><td><select><option>On</option><option>Off</option></select></td></tr>
            <tr><td>Bus</td><td>Type</td><td><select><option>BSB</option><option>LPB</option><option>PPS</option></select></td></tr>
            <tr><td>Network</td><td>Network connection</td><td><select><option>WiFi</option><option>LAN</option></select></td></tr>
            <tr><td>Network</td><td>WLAN SSID</td><td><input value="Example_IoT"></td></tr>
            <tr><td>Network</td><td>WLAN password</td><td><input type="password" value="sample-preview-only"></td></tr>
            <tr><td>Logging</td><td>Logging mode</td><td><label><input type="checkbox">Send to MQTT broker</label></td></tr>
            <tr><td>Logging</td><td>Interval (seconds)</td><td><input type="number" value="300"></td></tr>
            <tr><td>MQTT</td><td>Broker server</td><td><input value="192.0.2.10:1883"></td></tr></table></form>'''
        elif command.startswith('K'):
            content = '<table>'+''.join(f'<tr><td><a href="{prefix}{n}">{label}</a></td><td>{n}</td></tr>' for n,label in [('0-6','Date/Time'),('700-900','Heating circuit 1'),('5700-6699','Configuration'),('8700-9075','Diagnostics consumer'),('10000-11999','User defined'),('15000-15099','PPS bus'),('20000-20899','One Wire, DHT & MAX! Sensors')])+'</table>'
        css=(ROOT/'console.css').read_text(encoding='utf-8')
        js=(ROOT/'console.js').read_text(encoding='utf-8')
        html=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BSB-LAN Preview</title><style>{css}</style><script>{js}</script></head>
        <body><a class="skip-link" href="#app-main">Skip to content</a><header class="site-header"><div class="header-inner"><a class="brand" id="main_link" href="{prefix}"><strong>BSB-LAN</strong><span>/ Heating console</span></a><nav class="site-nav" aria-label="Main navigation">{links}<a href="https://docs.bsb-lan.de/">Manual</a></nav><span class="mode-status" id="write-mode">Read-only</span></div></header>
        <main id="app-main" data-supported="{supported}"><table class="legacy-page"><tr><td class="header">{content}</td></tr></table></main><footer class="site-footer"><span>BSB-LAN / Heating console</span><span>Preview data · Sample values for demonstration only</span></footer></body></html>'''
        return self.respond(html,'text/html')
    def do_POST(self):
        self.respond(json.dumps({'error':'Preview only. No storage operation was performed.'}),'application/json')
    def respond(self,data,content_type):
        body=data.encode();self.send_response(200);self.send_header('Content-Type',content_type+'; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

if __name__ == '__main__':
    print('UI preview http://127.0.0.1:8765/ · sample data only',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
