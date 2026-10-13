"""Template validation and boundary scenarios; not a running HA integration test."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import math
import yaml
from jinja2.nativetypes import NativeEnvironment

class Loader(yaml.SafeLoader):
    pass
Loader.add_constructor('!input', lambda loader,node: loader.construct_scalar(node))
data=yaml.load((Path(__file__).parent/'seasonal-budget.yaml').read_text(encoding='utf-8'),Loader=Loader)
assert data['blueprint']['domain']=='automation'
inputs=data['blueprint']['input']
weights=inputs['profile']['default']
assert len(weights)==12 and sum(weights)==63645 and weights[0]>weights[6]
env=NativeEnvironment()
def numeric(value):
    try:return math.isfinite(float(value))
    except (TypeError,ValueError):return False
values={'sensor.gas':'10','text.comfort':'21','input_number.applied':'19.5','input_boolean.active':'off'}
context={'gas_entity':'sensor.gas','setpoint_entity':'text.comfort','active_entity':'input_boolean.active',
         'applied_entity':'input_number.applied','weights':weights,'annual':63645,'mj_per_m3':35,
         'budget_fraction':0.9,'now':lambda:datetime(2026,1,16,tzinfo=timezone.utc),
         'states':lambda key:values.get(key,'unknown'),'state_attr':lambda entity,key:'m³',
         'is_state':lambda entity,state:values.get(entity)==state,'is_number':numeric,
         'timedelta':timedelta,'as_timestamp':lambda value:value.timestamp()}
def render(key):
    value=env.from_string(data['variables'][key]).render(**context)
    # Home Assistant strips template whitespace before parsing scalar results.
    if isinstance(value,str) and value.strip() in ('True','False'):
        return value.strip()=='True'
    return value
context['valid']=render('valid');assert context['valid'] is True
assert render('ahead') is False
values['sensor.gas']='400';assert render('ahead') is True
values['sensor.gas']='unavailable';context['valid']=render('valid');assert context['valid'] is False
assert render('ahead') is False
values['sensor.gas']='10';context['mj_per_m3']=0;assert render('valid') is False
context['mj_per_m3']=35;context['weights']=[0]*12;assert render('valid') is False
context['weights']={'a':1};assert render('valid') is False
context['weights']=weights;context['valid']=render('valid');context['target_now']=19.5
values['input_boolean.active']='on';assert render('owns') is True
context['target_now']=20;assert render('owns') is False
context['now']=lambda:datetime(2028,2,29,tzinfo=timezone.utc)
values['sensor.gas']='1';assert render('ahead') is False
def walk(value):
    if isinstance(value,dict):
        for child in value.values():walk(child)
    elif isinstance(value,list):
        for child in value:walk(child)
    elif isinstance(value,str) and ('{{' in value or '{%' in value):env.parse(value)
walk(data)
print('Budget YAML and templates passed 10 boundary checks; HA runtime remains unverified.')
