"""Existing BMS heating app: predictive planning, accounting and supervised policy output."""
from __future__ import annotations
import argparse
import json
import logging
from pathlib import Path
import queue
import signal
import time
from predictive.config import validate, DEFAULT
from predictive.telemetry import Store, Telemetry, TOPICS, PARAMETERS, Reading, finite, utc_timestamp
from predictive.engine import Engine
from predictive.supervisor import ProductionPublisher

LOG=logging.getLogger('bsb_optimizer')
ROOT='bms/heating_optimizer/'
IO='iopi/bmsiopi/'
INPUTS={IO+'heating_mode/state':'mode',IO+'pump_control/state':'pump_control',
        IO+'thermostat/state':'delta',IO+'relay_2/state':'pump_drive'}

METRICS={
 'status':('Optimizer state',None,None),'reason':('Heating decision',None,None),
 'daily_total':('Gas today · estimated fuel','kWh','energy'),
 'daily_heating':('Heating gas today · estimated fuel','kWh','energy'),
 'daily_dhw':('DHW gas today · estimated fuel','kWh','energy'),
 'daily_m3':('Gas today · billing conversion','m³','gas'),
 'annual_remaining':('Annual allowance remaining','kWh','energy'),
 'annual_projected':('Projected annual gas','kWh','energy'),
 'annual_cost':('Projected annual cost',None,None),
 'predicted_room':('Predicted room · next 15 min','°C','temperature'),
 'actual_room':('Room actual · measured','°C','temperature'),
 'matched_predicted_fuel':('Matched interval predicted fuel','kWh','energy'),
 'matched_actual_fuel':('Matched interval actual fuel','kWh','energy'),
 'predicted_fuel':('Planned room fuel · horizon','kWh','energy'),
 'tank_energy':('Useful tank energy · estimate','kWh','energy'),
 'tank_trend':('Tank B3 trend','°C/h',None),
 'cycle_minutes':('Average burner cycle','min',None),
 'model_rmse':('Model error','°C/h',None),
 'room_rmse':('Room prediction error','°C',None),
 'forecast_hours':('Hourly forecast coverage','h',None),
 'confidence':('Forecast confidence',None,None),'billing_status':('Billing readiness',None,None)}


def discovery(pub):
    for key,(name,unit,kind) in METRICS.items():
        row={'name':name,'unique_id':'bsb_optimizer_'+key,'state_topic':ROOT+'metric/'+key,
             'availability_topic':ROOT+'availability','payload_available':'online','payload_not_available':'offline',
             'device':{'identifiers':['bsb_optimizer'],'name':'Heating optimizer','manufacturer':'BMS','model':'RC MPC / HiGHS'},
             'expire_after':120,'value_template':'{{ value if value != "null" else none }}'}
        row['default_entity_id']='sensor.bsb_optimizer_'+key
        if unit: row['unit_of_measurement']=unit
        if kind: row['device_class']=kind
        pub.publish('homeassistant/sensor/bsb_optimizer/'+key+'/config',json.dumps(row),True)


def publish_report(pub,report):
    p=report['plan']; first=p['plan'][0] if p['plan'] else {}
    values={k:report[k] for k in ('status','reason','daily_m3','confidence','billing_status')}
    values.update(daily_total=report['daily']['8380']['kwh'],daily_heating=report['daily']['8378']['kwh'],
      daily_dhw=report['daily']['8379']['kwh'],annual_remaining=report['annual'].get('remaining_kwh'),
      annual_projected=report['annual'].get('projected_kwh'),annual_cost=report['annual'].get('cost'),
      predicted_room=first.get('room_c'),actual_room=report['actual_room_c'],
      matched_predicted_fuel=report['comparison'].get('value'),matched_actual_fuel=report['comparison'].get('actual'),
      predicted_fuel=p.get('fuel_kwh'),tank_energy=report['tank'].get('useful_kwh'),
      tank_trend=report['tank_trend_c_h'],cycle_minutes=report['cycling']['average_cycle_minutes'],
      model_rmse=report['model'].get('rmse_c_per_hour'),room_rmse=report['accuracy']['room']['rmse'],
      forecast_hours=report['hourly_forecast_hours'])
    for key,value in values.items():
        if isinstance(value,float): value=round(value,3)
        pub.publish(ROOT+'metric/'+key,'null' if value is None else str(value),False)
    pub.publish(ROOT+'state',json.dumps(report,allow_nan=False),False)
    pub.publish(ROOT+'recommendation',json.dumps(report['recommendation'],allow_nan=False),False)


def run(config_path,credentials_path,database):
    import paho.mqtt.client as mqtt
    cfg=validate(json.loads(Path(config_path).read_text(encoding='utf8')))
    credentials=json.loads(Path(credentials_path).read_text(encoding='utf8'))
    store=Store(database); telemetry=Telemetry(store); engine=Engine(store,telemetry,cfg)
    saved_weather=store.get_state('weather')
    if saved_weather:
        try: engine.ingest_forecast(saved_weather,time.time())
        except (ValueError,KeyError,TypeError): pass
    incoming=queue.Queue(maxsize=4096); running=True; connected=False
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='bsb-heating-optimizer')
    client.username_pw_set(credentials['username'],credentials['password'])
    if credentials.get('ca_file'): client.tls_set(ca_certs=credentials['ca_file'])
    client.will_set(ROOT+'availability','offline',qos=1,retain=True)
    client.max_queued_messages_set(64); client.max_inflight_messages_set(10)
    pub=ProductionPublisher(lambda topic,payload,retain: client.publish(topic,payload,qos=1,retain=retain))
    external={row['topic']:(key,row) for key,row in cfg['external_sensors'].items()}
    def on_connect(c,userdata,flags,reason,properties):
        nonlocal connected
        connected=not reason.is_failure
        if connected:
            for topic in [*TOPICS,*INPUTS,*external,ROOT+'weather',ROOT+'context',ROOT+'settings']:
                c.subscribe(topic,qos=1)
            pub.publish(ROOT+'availability','online',True); discovery(pub)
    def on_disconnect(c,userdata,flags,reason,properties):
        nonlocal connected
        connected=False
    def on_message(c,userdata,message):
        if len(message.payload)>250000: return
        # Retained device states have no trustworthy acquisition timestamp. Poll fresh.
        if message.retain and (message.topic in TOPICS or message.topic in INPUTS or message.topic in external): return
        try: incoming.put_nowait((message.topic,message.payload.decode('utf8'),time.time()))
        except (queue.Full,UnicodeError): LOG.warning('Input queue full or invalid UTF-8')
    def stop(signum,frame):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    client.on_connect=on_connect; client.on_disconnect=on_disconnect; client.on_message=on_message
    client.reconnect_delay_set(1,30)
    client.connect_async(credentials['host'],credentials.get('port',1883),keepalive=30); client.loop_start()
    next_tick=0; next_poll=0; poll_index=0; polls=list(TOPICS)
    try:
        while running:
            now=time.time()
            for _ in range(100):
                try: topic,payload,at=incoming.get_nowait()
                except queue.Empty: break
                try:
                    if topic in TOPICS: telemetry.ingest(TOPICS[topic],payload,at)
                    elif topic in INPUTS: telemetry.ingest(INPUTS[topic],payload,at)
                    elif topic in external:
                        key,row=external[topic]; data=json.loads(payload)
                        measured=utc_timestamp(data['at'])
                        if not 0<=at-measured<=180 or data['unit']!=row['unit']: raise ValueError('External sensor stale / unit mismatch')
                        value=finite(data['value'])
                        if not row.get('minimum',-60)<=value<=row.get('maximum',140): raise ValueError('External sensor range')
                        telemetry.ingest(key,value,measured,row['unit'],'verified_external_measurement')
                    elif topic==ROOT+'weather':
                        engine.ingest_forecast(json.loads(payload),at)
                        if engine.forecast.current is not None:
                            telemetry.ingest('outdoor_estimate',engine.forecast.current,at,'°C','weather_estimate')
                    elif topic==ROOT+'context': engine.context(json.loads(payload),at)
                    elif topic==ROOT+'settings': engine.settings(json.loads(payload))
                except (ValueError,KeyError,TypeError,OverflowError) as exc:
                    LOG.warning('Rejected %s: %s',topic,str(exc)[:160]); store.event(at,'rejected_input',topic+': '+str(exc))
            if connected and now>=next_poll:
                # Separate read-only capability: explicit known status/poll allowlist, no /set.
                topic=polls[poll_index%len(polls)].removesuffix('/status')+'/poll'
                client.publish(topic,'',qos=0,retain=False)
                poll_index+=1; next_poll=now+3
            if connected and now>=next_tick:
                report=engine.tick(now); publish_report(pub,report)
                LOG.info('%s: %s',report['status'],report['reason']); next_tick=now+30
            time.sleep(.2)
    finally:
        pub.publish(ROOT+'availability','offline',True)
        client.disconnect(); client.loop_stop(); store.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='/etc/bsb-optimizer/config.json')
    parser.add_argument('--credentials',default='/etc/bsb-optimizer/mqtt.json')
    parser.add_argument('--database',default='/var/lib/bsb-optimizer/heating.sqlite3')
    parser.add_argument('--check-config',action='store_true')
    args=parser.parse_args(); logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if args.check_config:
        validate(json.loads(Path(args.config).read_text(encoding='utf8'))); print('Configuration valid'); return
    run(args.config,args.credentials,args.database)

if __name__=='__main__': main()
