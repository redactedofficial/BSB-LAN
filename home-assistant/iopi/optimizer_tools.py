"""Offline tools. No MQTT/IO-PI/boiler module is imported by this entry point."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from predictive.config import validate
from predictive.telemetry import Store, Telemetry, PARAMETERS, Reading
from predictive.budget import import_bills
from predictive.engine import Engine
from predictive.supervisor import SimulationPublisher


ENTITIES={
  8310:'sensor.bsb_lan_00_36_diagnostics_producer_8310_boiler_temp_actual_value',
  8314:'sensor.bsb_lan_00_36_diagnostics_producer_8314_return_temp_actual_value',
  8830:'sensor.bsb_lan_00_37_diagnostics_consumer_8830_dhw_temperature_actual_value_top_b3',
  8378:'sensor.bsb_lan_00_36_diagnostics_producer_8378_energy_gas_heating',
  8379:'sensor.bsb_lan_00_36_diagnostics_producer_8379_energy_gas_dhw',
  8380:'sensor.bsb_lan_00_36_diagnostics_producer_8380_energy_gas',
  8740:'sensor.bsb_lan_00_37_diagnostics_consumer_8740_room_temperature_1',
  8700:'sensor.bsb_lan_00_37_diagnostics_consumer_8700_outside_temperature'}

def import_recorder(source,target,days=35,now=None):
    """Read-only HA recorder with explicit identities; never write or migrate it."""
    now=now or datetime.now(timezone.utc).timestamp()
    db=sqlite3.connect('file:'+str(Path(source).resolve()).replace('\\','/')+'?mode=ro',uri=True,timeout=10)
    db.row_factory=sqlite3.Row
    actual={r['entity_id']:r['metadata_id'] for r in db.execute('SELECT * FROM states_meta')}
    # Names vary across BSB discovery versions. Parameter + category must both match uniquely.
    for p,(cat,unit,quality) in PARAMETERS.items():
        candidates=[(entity,mid) for entity,mid in actual.items() if f'_{p}_' in entity and 'bsb_lan_' in entity and f'_00_{cat}_' in entity]
        if len(candidates)!=1 or unit=='enum': continue
        _,mid=candidates[0]
        rows=db.execute('SELECT s.state,s.last_updated_ts,a.shared_attrs FROM states s LEFT JOIN state_attributes a ON a.attributes_id=s.attributes_id WHERE s.metadata_id=? AND s.last_updated_ts>=? AND s.last_updated_ts<=? ORDER BY s.last_updated_ts',(mid,now-days*86400,now)).fetchall()
        for row in rows:
            at=row['last_updated_ts']
            try: value=float(row['state'])
            except (ValueError,TypeError): continue
            if p in (8378,8379,8380):
                # Recorder state attributes confirm energy units instead of trusting an entity label.
                measured_unit=json.loads(row['shared_attrs'] or '{}').get('unit_of_measurement')
                if measured_unit!=unit: continue
            target.record(str(p),Reading(value,at,unit,quality))
    db.close()
    # Build canonical counter intervals in UTC order exactly once; restarts retain their baseline.
    count=0
    for key in ('8378','8379','8380'):
        for row in target.db.execute('SELECT at,value,unit FROM observations WHERE key=? ORDER BY at',(key,)).fetchall():
            if json.loads(row['value']) is not None:
                target.counter(key,row['at'],json.loads(row['value']),row['unit']); count+=1
    return count

def backtest(source,config,output):
    # Open production history read-only. Replay into a fresh throwaway store, never the live database.
    db=sqlite3.connect('file:'+str(Path(source).resolve()).replace('\\','/')+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    publisher=SimulationPublisher(); summaries=[]
    with tempfile.TemporaryDirectory(prefix='bsb-backtest-') as directory:
        store=Store(str(Path(directory)/'simulation.sqlite3')); telemetry=Telemetry(store)
        engine=Engine(store,telemetry,dict(config,mode='shadow',automatic_control_commissioned=False))
        next_tick=0
        for row in db.execute('SELECT * FROM observations ORDER BY at,key'):
            value=json.loads(row['value']); at=row['at']
            if row['key']=='weather_forecast':
                try: engine.ingest_forecast(value,at)
                except (ValueError,KeyError,TypeError): continue
            else: telemetry.ingest(row['key'],value,at,row['unit'],row['quality'])
            if at>=next_tick:
                report=engine.tick(at)
                message={'at':at,'status':report['status'],'plan_status':report['plan']['status'],
                   'reason':report['reason'],'actual_room_c':report['actual_room_c'],'accuracy':report['accuracy']}
                publisher.publish('simulation/heating/report',json.dumps(message))
                summaries.append(message); next_tick=at+900
        store.close()
    db.close()
    result={'isolated':True,'physical_commands':0,'samples':len(summaries),
            'forecast_policy':'Only forecasts recorded at or before replay time; no future weather leakage',
            'results':summaries}
    Path(output).write_text(json.dumps(result,indent=2),encoding='utf8')
    return result

def main():
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest='action',required=True)
    for name in ('import-recorder','import-bills','backtest'):
        command=sub.add_parser(name); command.add_argument('--database',required=True)
        command.add_argument('--input' if name!='backtest' else '--config',required=True)
        if name=='backtest': command.add_argument('--output',required=True)
    args=parser.parse_args()
    if args.action=='backtest':
        result=backtest(args.database,validate(json.loads(Path(args.config).read_text(encoding='utf8'))),args.output)
        print(json.dumps({k:v for k,v in result.items() if k!='results'})); return
    store=Store(args.database)
    if args.action=='import-recorder': count=import_recorder(args.input,store)
    else: count=import_bills(store,json.loads(Path(args.input).read_text(encoding='utf8')))
    store.close(); print('Imported records:',count)

if __name__=='__main__': main()
