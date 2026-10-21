"""Extend the existing HA coordinator; never introduce another actuator owner."""
import json
from pathlib import Path
import yaml
from predictive.config import DEFAULT

ROOT=Path(__file__).parent

def build():
    path=ROOT/'daily-heating.yaml'
    package=yaml.safe_load(path.read_text(encoding='utf8'))
    sequence=package['script']['bsb_heat_control']['sequence']
    # Idempotent rebuild: remove our context/variables before inserting refreshed versions.
    sequence[:]=[s for s in sequence if s.get('data',{}).get('topic')!='bms/heating_optimizer/context'
                 and 'optimizer_fresh' not in s.get('variables',{})]
    for step in sequence:
        if step.get('action')=='calendar.get_events':
            step['data']['end_date_time']='{{ (now() + timedelta(days=2)).isoformat() }}'
        v=step.get('variables',{})
        if 'weather_blocked' in v:
            v['weather_blocked']="{{ is_state('input_boolean.bsb_weather_gate_enabled', 'on') and is_number(states('sensor.bsb_outdoor_weather_estimate')) and is_number(states('input_number.bsb_heating_weather_limit')) and states('sensor.bsb_outdoor_weather_estimate') | float >= states('input_number.bsb_heating_weather_limit') | float }}"
        if 'reason' in v: v['reason']=v['reason'].replace('Outdoor weather warm or unavailable','Outdoor weather warm')
    index=next(i for i,s in enumerate(sequence) if s.get('data',{}).get('topic')=='iopi/bmsiopi/heating/policy/set')
    context="""{% set ns = namespace(events=[]) %}{% for e in calendar_result.get('calendar.heating', {}).get('events', []) %}{% if e.start | string | length > 10 and e.end | string | length > 10 %}{% set ns.events = ns.events + [{'start': as_timestamp(e.start, 0), 'end': as_timestamp(e.end, 0)}] %}{% endif %}{% endfor %}{{ {'allowed': allowed, 'gas_allowed': allowed and calendar_ok and window_active, 'target': states('input_number.bsb_calendar_hot_target') | float(45), 'expires': permission_expires, 'events': ns.events, 'cold_enabled': is_state('input_boolean.bsb_cold_boost_enabled','on') and is_state('input_boolean.bsb_weather_gate_enabled','on'), 'cold_limit_c': states('input_number.bsb_cold_boost_temperature') | float(-99), 'cold_overnight': is_state('input_boolean.bsb_cold_boost_overnight','on')} | to_json }}"""
    sequence[index:index]=[
       {'action':'mqtt.publish','data':{'topic':'bms/heating_optimizer/context','retain':False,'payload':context}},
       {'variables':{
         'optimizer_fresh':"{{ state_attr('sensor.bsb_predictive_recommendation','authoritative') == true and state_attr('sensor.bsb_predictive_recommendation','schema') == 1 and is_state('input_select.bsb_optimizer_mode','production') and is_number(state_attr('sensor.bsb_predictive_recommendation','issued_at')) and is_number(state_attr('sensor.bsb_predictive_recommendation','expires')) and 0 <= as_timestamp(now()) - state_attr('sensor.bsb_predictive_recommendation','issued_at') | float(-999) < 75 and as_timestamp(now()) < state_attr('sensor.bsb_predictive_recommendation','expires') | float(0) <= as_timestamp(now()) + 75 and state_attr('sensor.bsb_predictive_recommendation','allow_gas') in [true,false] and state_attr('sensor.bsb_predictive_recommendation','allow_pump') in [true,false] and is_number(state_attr('sensor.bsb_predictive_recommendation','return_target')) and 30 <= state_attr('sensor.bsb_predictive_recommendation','return_target') | float(0) <= 55 }}",
         'effective_allowed':"{{ allowed and (not optimizer_fresh or state_attr('sensor.bsb_predictive_recommendation','allow_pump') == true) }}",
         'effective_gas':"{{ allowed and calendar_ok and window_active and (not optimizer_fresh or state_attr('sensor.bsb_predictive_recommendation','allow_gas') == true) }}",
         'effective_target':"{{ state_attr('sensor.bsb_predictive_recommendation','return_target') | float(45) if optimizer_fresh else states('input_number.bsb_calendar_hot_target') | float(45) }}"}}]
    policy=sequence[index+2]['data']
    policy['payload']="{{ {'allowed': effective_allowed, 'gas_allowed': effective_gas, 'buffer_preferred': is_state('input_boolean.iopi_prefer_stored_heat','on'), 'buffer_window': buffer_window, 'buffer_minimum': states('input_number.iopi_buffer_minimum') | float(40), 'buffer_differential': 5, 'target': effective_target, 'differential': states('input_number.bsb_calendar_hysteresis') | float(2), 'expires': permission_expires, 'reason': (state_attr('sensor.bsb_predictive_recommendation','reason') if optimizer_fresh else reason)} | to_json }}"
    path.write_text(yaml.safe_dump(package,sort_keys=False,allow_unicode=True,width=110),encoding='utf8')
    mqtt_sensors=[{'name':'BSB predictive report','unique_id':'bsb_predictive_report','state_topic':'bms/heating_optimizer/state',
        'value_template':'{{ value_json.status }}','json_attributes_topic':'bms/heating_optimizer/state',
        'json_attributes':['reason','daily','annual','weather_days','hourly_forecast_hours','plan','model','accuracy','tank','tank_trend_c_h','solar_evidence','cycling','missing_sensors','telemetry','actual_room_c','heat_kw','comparison','confidence','billing_status'],
        'expire_after':120},
       {'name':'BSB predictive recommendation','unique_id':'bsb_predictive_recommendation',
        'state_topic':'bms/heating_optimizer/recommendation','value_template':'{{ value_json.mode }}',
        'json_attributes_topic':'bms/heating_optimizer/recommendation',
        'json_attributes':['schema','issued_at','expires','authoritative','allow_gas','allow_pump','return_target','reason'],'expire_after':90}]
    # MQTT uses the JSON object itself for attributes; it has no json_attributes list option.
    for sensor in mqtt_sensors: sensor.pop('json_attributes',None)
    forecast_steps=[{'variables':{'hourly_result':{},'daily_result':{}}}]
    for name in ('hourly','daily'):
        forecast_steps.append({'action':'weather.get_forecasts','continue_on_error':True,
            'target':{'entity_id':'weather.forecast_home'},'data':{'type':name},'response_variable':name+'_result'})
    forecast_steps.append({'action':'mqtt.publish','data':{'topic':'bms/heating_optimizer/weather','retain':False,
        'payload':"{{ {'generated_at': now().isoformat(), 'source': 'Home Assistant: weather.forecast_home', 'temperature_unit': state_attr('weather.forecast_home','temperature_unit'), 'wind_speed_unit': state_attr('weather.forecast_home','wind_speed_unit'), 'current_temperature': state_attr('weather.forecast_home','temperature'), 'hourly': hourly_result.get('weather.forecast_home',{}).get('forecast',[]), 'daily': daily_result.get('weather.forecast_home',{}).get('forecast',[])} | to_json }}"}})
    settings={'action':'mqtt.publish','data':{'topic':'bms/heating_optimizer/settings','retain':False,
      'payload':"{{ {'mode': states('input_select.bsb_optimizer_mode'), 'comfort_c': states('input_number.bsb_optimizer_comfort') | float(18), 'preferred_daily_m3': states('input_number.bsb_optimizer_preferred') | float(5), 'soft_ceiling_m3': states('input_number.bsb_optimizer_ceiling') | float(7), 'risk_margin': states('input_number.bsb_optimizer_risk') | float(0.5)} | to_json }}"}}
    numbers={}
    for key,name,lo,hi,step,unit in [('comfort','Room comfort',12,23,.5,'°C'),('preferred','Preferred daily gas',0,50,.5,'m³'),('ceiling','Soft daily gas ceiling',0,100,.5,'m³'),('risk','Forecast caution',0,2,.1,None)]:
        numbers['bsb_optimizer_'+key]={'name':name,'min':lo,'max':hi,'step':step,'mode':'box'}
        if unit: numbers['bsb_optimizer_'+key]['unit_of_measurement']=unit
    init=[{'condition':'state','entity_id':'input_boolean.bsb_optimizer_initialized','state':'off'}]
    for key,value in [('comfort',18),('preferred',5),('ceiling',7),('risk',.5)]:
        init.append({'action':'input_number.set_value','target':{'entity_id':'input_number.bsb_optimizer_'+key},'data':{'value':value}})
    init.append({'action':'input_boolean.turn_on','target':{'entity_id':'input_boolean.bsb_optimizer_initialized'}})
    result={'input_boolean':{'bsb_optimizer_initialized':{'name':'Optimizer preferences initialized'}},
      'input_select':{'bsb_optimizer_mode':{'name':'Optimizer mode','options':['production','shadow','disabled'],'icon':'mdi:brain'}},
      'input_number':numbers,'mqtt':{'sensor':mqtt_sensors},'automation':[
        {'id':'bsb_optimizer_initialize','alias':'BMS optimizer initial preferences','triggers':[{'trigger':'homeassistant','event':'start'}],'actions':init},
        {'id':'bsb_optimizer_weather','alias':'BMS optimizer forecast refresh','mode':'single',
         'triggers':[{'trigger':'homeassistant','event':'start'},{'trigger':'time_pattern','minutes':'/15'}],
         'actions':forecast_steps},
        {'id':'bsb_optimizer_settings','alias':'BMS optimizer preferences','mode':'restart',
         'triggers':[{'trigger':'homeassistant','event':'start'},{'trigger':'time_pattern','minutes':'/5'},
           {'trigger':'state','entity_id':['input_select.bsb_optimizer_mode',*['input_number.'+k for k in numbers]]}],
         'actions':[settings]}]}
    (ROOT/'predictive-heating.yaml').write_text(yaml.safe_dump(result,sort_keys=False,allow_unicode=True,width=110),encoding='utf8')
    (ROOT/'optimizer-config.example.json').write_text(json.dumps(DEFAULT,indent=2)+'\n',encoding='utf8')

if __name__=='__main__': build()
