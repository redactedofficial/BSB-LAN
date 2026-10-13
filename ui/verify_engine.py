"""Check that the retained protocol/decoder implementation matches pinned upstream."""
from pathlib import Path
import re
import subprocess

root=Path(__file__).resolve().parent.parent
baseline='d3f748f468c30e139bb29e9e9a76c6250a04a519'
def original(path):
    return subprocess.check_output(['git','show',baseline+':'+path],cwd=root).decode('utf-8').replace('\r\n','\n')
for path in ['BSB_LAN/BSB_LAN_defs.h','BSB_LAN/src/BSB/bsb.cpp','BSB_LAN/src/BSB/bsb.h','BSB_LAN/include/mqtt_handler.h']:
    assert (root/path).read_text(encoding='utf-8').replace('\r\n','\n')==original(path),path
def function(text,name):
    masked=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda match:re.sub(r'[^\n]',' ',match.group()),text,flags=re.S)
    match=re.search(r'^\s*[\w*]+(?:\s+[\w*]+)*\s+'+name+r'\s*\([^;{}]*?\)\s*\{',masked,flags=re.M)
    assert match,name
    start=masked.index('{',match.start());depth=1;end=start+1
    while depth:
        depth+=(masked[end]=='{')-(masked[end]=='}');end+=1
    return text[match.start():end].strip()
before=original('BSB_LAN/BSB_LAN.ino')
after=(root/'BSB_LAN/BSB_LAN.ino').read_text(encoding='utf-8').replace('\r\n','\n')
for name in ['set','query','findLine','GetDevId','programIsreadOnly','loadPrognrElementsFromTable']:
    assert function(before,name)==function(after,name),name
print('Bus, definitions and MQTT unchanged; 6 core decoder/control functions match upstream.')
