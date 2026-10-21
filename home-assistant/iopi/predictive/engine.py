"""One app-owned planner. All hardware control remains in the existing HA/IO-PI owners."""
from datetime import datetime, timedelta
import json
import math
import numpy as np
from .telemetry import LOCAL, Reading, local_day_bounds, finite
from .weather import Forecast
from .thermal import Identification, tank_energy, delivered_power, cycling
from .budget import AnnualPlanner, conversion_at, volume_between, tariff_cost
from .mpc import solve
from .supervisor import SafetySupervisor
from .config import validate


class Engine:
    def __init__(self, store, telemetry, config):
        self.store,self.telemetry=store,telemetry
        self.original=validate(config); self.config=dict(self.original)
        self.ident=Identification(store.get_state('identification'))
        self.forecast=None; self.base={}; self.proposal={'status':'fallback','reason':'Waiting for validated inputs','plan':[]}
        self.last_slot=None; self.last_sample=None
        self.last_plan_at=0
        self.dailyfit=None; self.dailyfit_at=0
        self.settings(store.get_state('settings',{}),persist=False)

    def settings(self, row, persist=True):
        if not isinstance(row,dict): raise ValueError('Settings object required')
        allowed=('mode','comfort_c','preferred_daily_m3','soft_ceiling_m3','risk_margin')
        if set(row)-set(allowed): raise ValueError('Unsupported runtime setting')
        next_config=dict(self.config); next_config.update(row)
        changed=any(self.config.get(k)!=v for k,v in row.items())
        self.config=validate(next_config)
        if persist: self.store.set_state('settings',row)
        if changed: self.last_slot=None

    def ingest_forecast(self,payload,now):
        candidate=Forecast(payload,now)
        if self.forecast and self.forecast.points and candidate.points and abs(self.forecast.points[0].temperature-candidate.points[0].temperature)>=5:
            self.last_slot=None
        self.forecast=candidate
        self.store.set_state('weather',payload)
        self.store.record('weather_forecast',Reading(payload,now,'forecast','provider_forecast'))

    def context(self,row,now):
        if not isinstance(row,dict): raise ValueError('Context object required')
        expires=finite(row.get('expires',0))
        if not now<expires<=now+90: raise ValueError('Context lease')
        for k in ('allowed','gas_allowed'):
            if type(row.get(k)) is not bool: raise ValueError('Invalid context flag')
        if not 30<=finite(row.get('target',0))<=55: raise ValueError('Invalid return target')
        self.base=row

    def actual_room(self,now):
        value=self.telemetry.value('room_actual',now)
        return value if value is not None else self.telemetry.value('8740',now)

    def measured_heat(self,now):
        t=self.telemetry; cfg=self.config
        heat=t.value('delivered_kw',now)
        if heat is not None: return heat,'measured heat meter'
        heat=delivered_power(t.value('flow_m3h',now),t.value('supply_actual',now),
                             t.value('return_actual',now),cfg['flow_verified'])
        return heat,'verified flow × water temperature difference' if heat is not None else 'unavailable'

    def learn(self,now):
        room=self.actual_room(now)
        outdoor=self.telemetry.value('8700',now)
        if outdoor is None and self.forecast and now-self.forecast.generated<5400: outdoor=self.forecast.current
        heat,source=self.measured_heat(now)
        # Fuel estimates are explicitly opt-in and use a commissioned efficiency only.
        sample={'at':now,'room':room,'outdoor':outdoor,'heat':heat,'source':source}
        old=self.last_sample
        if old is None: self.last_sample=sample; return
        elapsed=now-old['at']
        if elapsed<900: return
        trusted=heat is not None and old['heat'] is not None
        q=(heat+old['heat'])/2 if trusted else None
        if not trusted and self.config['allow_estimated_heat_identification'] and self.config['efficiency']:
            gas=self.store.energy('8378',old['at'],now)
            if gas['coverage']>=.98 and gas['kwh'] is not None:
                q=gas['kwh']*3600/elapsed*self.config['efficiency']; trusted=True
        if None not in (room,outdoor,old['room'],old['outdoor']) and elapsed<=3600:
            weather=self.forecast.horizon(now,1) if self.forecast else []
            point=weather[0] if weather else None
            self.ident.update(old['room'],room,(outdoor+old['outdoor'])/2,q,elapsed/3600,
                point.solar_w_m2 or 0 if point else 0,point.wind_ms or 0 if point else 0,trusted)
            self.store.set_state('identification',self.ident.state())
        self.last_sample=sample

    def seasonal_fit(self,now):
        """Daily degree-day regression from completed, covered historical days only."""
        rows=[]; dhw=[]
        today=datetime.fromtimestamp(now,LOCAL).date()
        for offset in range(1,36):
            start,end=local_day_bounds((today-timedelta(days=offset)).isoformat())
            h=self.store.energy('8378',start,end); d=self.store.energy('8379',start,end)
            observations=self.store.db.execute("SELECT value FROM observations WHERE key IN ('8700','outdoor_estimate') AND at>=? AND at<?",(start,end)).fetchall()
            temps=[json.loads(r[0]) for r in observations if json.loads(r[0]) is not None]
            if h['coverage']>.98 and len(temps)>=12 and h['kwh'] is not None:
                dd=max(0,self.config['comfort_c']-sum(temps)/len(temps))
                rows.append((dd,h['kwh']))
            if d['coverage']>.98 and d['kwh'] is not None: dhw.append(d['kwh'])
        slope=None
        if len(rows)>=7 and max(r[0] for r in rows)-min(r[0] for r in rows)>=3:
            x=np.array([r[0] for r in rows]); y=np.array([r[1] for r in rows])
            slope=float(x@y/(x@x)) if x@x>0 else None
            if slope is not None and not 0<=slope<=100: slope=None
        return {'kwh_per_degree_day':slope,'days':len(rows)},sum(dhw)/len(dhw) if len(dhw)>=7 else None

    def feedback_predictions(self,now):
        for row in self.store.db.execute('SELECT issued,target,kind FROM predictions WHERE actual IS NULL AND target<=? AND target>?',(now,now-172800)).fetchall():
            target=row['target']; actual=None
            if row['kind']=='room':
                found=self.store.db.execute("SELECT value FROM observations WHERE key IN ('8740','room_actual') AND at BETWEEN ? AND ? AND value!='null' ORDER BY ABS(at-?) LIMIT 1",(target-180,target+180,target)).fetchone()
                if found: actual=json.loads(found[0])
            elif row['kind']=='fuel':
                usage=self.store.energy('8378',target-900,target)
                if usage['coverage']>.98: actual=usage['kwh']
            if actual is not None:
                self.store.db.execute('UPDATE predictions SET actual=? WHERE issued=? AND target=? AND kind=?',(actual,row['issued'],target,row['kind']))
        self.store.db.commit()

    def cycle_report(self,now):
        values=[]
        for key in ('8330','8331'):
            rows=self.store.db.execute('SELECT value FROM observations WHERE key=? AND at>? AND value!="null" ORDER BY at',(key,now-86400)).fetchall()
            values.append(json.loads(rows[-1][0])-json.loads(rows[0][0]) if len(rows)>1 else None)
        return cycling(*values)

    def tick(self,now,force=False):
        self.learn(now); self.feedback_predictions(now)
        cfg=self.config; t=self.telemetry
        weather=self.forecast if self.forecast and 0<=now-self.forecast.generated<=5400 else None
        points=weather.horizon(now,cfg['horizon_hours']) if weather else []
        days=weather.seven_days(now) if weather else []
        room=self.actual_room(now)
        model=self.ident.parameters()
        if cfg['approved_model']: model=dict(cfg['approved_model'],calibrated=True,quality='commissioned model')
        ready=room is not None and model.get('calibrated') and cfg['efficiency'] is not None
        tank=tank_energy(cfg['tank_volume_l'],[t.value(k,now) for k in cfg['tank_sensor_keys']],
                         cfg['tank_reference_c'],cfg['tank_average_verified'],cfg.get('tank_weights'))
        if self.dailyfit is None or now-self.dailyfit_at>=3600:
            self.dailyfit=self.seasonal_fit(now); self.dailyfit_at=now
        slope,dhw=self.dailyfit
        annual=AnnualPlanner(self.store,cfg['billing']).forecast(now,days,slope,dhw,cfg['comfort_c'])
        slot=int(now//900)
        if force or slot!=self.last_slot:
            self.last_slot=slot
            if ready and len(points)>=24 and cfg['mode']!='disabled':
                settings=dict(cfg)
                settings['kwh_per_m3']=conversion_at(cfg['billing'],now)
                today=datetime.fromtimestamp(now,LOCAL).date().isoformat()
                settings['used_kwh_by_local_day']={today:self.store.today(now)['kwh'] or 0}
                if annual.get('projected_kwh') and annual.get('allowance_kwh'):
                    settings['budget_pressure']=max(0,annual['projected_kwh']/annual['allowance_kwh']-1)
                bands=cfg['billing'].get('tariffs',[])
                if bands:
                    known=annual.get('known_consumption_kwh',0)
                    a,b=tariff_cost(known,cfg['billing']),tariff_cost(known+1,cfg['billing'])
                    if a is not None and b is not None: settings['price_per_kwh']=b-a
                # Never forecast unscheduled gas permission; cold windows need actual forecast support.
                events=self.base.get('events',[])
                cold_limit=self.base.get('cold_limit_c',-99)
                masks=[]
                for i in range(len(points)*4):
                    at=now+i*900; local=datetime.fromtimestamp(at,LOCAL)
                    scheduled=any(e['start']<=at<e['end'] for e in events)
                    cold=points[i//4].temperature<=cold_limit and self.base.get('cold_enabled',False) and (self.base.get('cold_overnight',False) or 6<=local.hour<22)
                    masks.append(scheduled or cold)
                self.proposal=solve(room,points,model,settings,tank.get('useful_kwh') or 0,masks)
                self.proposal['outside_c']=points[0].temperature
            else:
                self.proposal={'status':'fallback','reason':'Actual room temperature, calibrated heat model, efficiency and 24h forecast required','plan':[]}
            self.last_plan_at=now
            self.store.db.execute('INSERT OR REPLACE INTO plans VALUES(?,?,?)',(slot,now,json.dumps(self.proposal)))
            for index,row in enumerate(self.proposal['plan']):
                # Dense first-hour validation plus hourly later horizons bounds history growth.
                if index>=4 and index%4: continue
                for kind,value in (('room',row['room_c']),('fuel',row['gas_input_kw']*.25)):
                    self.store.db.execute('INSERT OR IGNORE INTO predictions VALUES(?,?,?,?,NULL)',(now,row['at']+900,kind,value))
            self.store.db.commit(); self.store.prune(now)
        # A new current observation can invalidate a plan; never reuse stale room/model/forecast.
        proposal=self.proposal if weather and ready and now-self.last_plan_at<900 else {'status':'fallback','reason':'Inputs or plan stale','plan':[]}
        # External measured room reading is exposed to the same independent gate as native 8740.
        if room is not None and t.value('8740',now) is None:
            t.readings['8740']=Reading(room,t.readings['room_actual'].at,'°C','verified_external_measurement')
        recommendation=SafetySupervisor(cfg).validate(proposal,t,now,self.base,ready)
        first=proposal.get('plan',[{}])[0] if proposal.get('plan') else {}
        start,end=local_day_bounds(datetime.fromtimestamp(now,LOCAL).date().isoformat())
        daily={k:self.store.today(now,k) for k in ('8378','8379','8380')}
        accuracy={}
        for key in ('room','fuel'):
            row=self.store.db.execute('SELECT AVG((value-actual)*(value-actual)),COUNT(*) FROM predictions WHERE kind=? AND actual IS NOT NULL AND issued>?',(key,now-7*86400)).fetchone()
            accuracy[key]={'rmse':math.sqrt(row[0]) if row[0] is not None else None,'samples':row[1]}
        matched=self.store.db.execute('SELECT target,value,actual FROM predictions WHERE kind="fuel" AND actual IS NOT NULL ORDER BY target DESC,issued DESC LIMIT 1').fetchone()
        missing=[str(p) for p in (8740,8700,8980,8982,8983,8510,8519,8520) if t.value(str(p),now) is None]
        trend_rows=self.store.db.execute('SELECT at,value FROM observations WHERE key="8830" AND at>? AND value!="null" ORDER BY at',(now-3600,)).fetchall()
        trend=None
        if len(trend_rows)>=2 and trend_rows[-1]['at']-trend_rows[0]['at']>=900:
            trend=(json.loads(trend_rows[-1]['value'])-json.loads(trend_rows[0]['value']))*3600/(trend_rows[-1]['at']-trend_rows[0]['at'])
        evidence='No confirmed solar heat measurement'
        if trend is not None and trend>.5:
            activity=self.store.db.execute("SELECT key,value FROM observations WHERE key IN ('8005','8009','8820','pump_drive') AND at>?",(now-3600,)).fetchall()
            values=[(r['key'],json.loads(r['value'])) for r in activity]
            all_idle=all(any(k==required for k,v in values) for required in ('8005','8009','pump_drive')) and all(
                v==25 if k=='8005' else v==216 if k=='8009' else v in (0,'OFF') for k,v in values)
            evidence=('Tank warming with burner and circulation idle; possible solar/passive input, unconfirmed' if all_idle else
                      'Tank warming; boiler or circulation may explain rise; solar unconfirmed')
        return {'at':now,'mode':cfg['mode'],'status':'MPC active' if recommendation['authoritative'] else 'Production fallback' if cfg['mode']=='production' else cfg['mode'].title(),
            'reason':recommendation['reason'],'recommendation':recommendation,'daily':daily,
            'daily_m3':volume_between(self.store,cfg['billing'],start,now),
            'annual':annual,'weather_days':days,'hourly_forecast_hours':len(points),
            'plan':self.proposal,'model':model,'accuracy':accuracy,'tank':tank,'tank_trend_c_h':trend,
            'solar_evidence':evidence,
            'cycling':self.cycle_report(now),'missing_sensors':missing,'telemetry':t.report(now),
            'actual_room_c':room,'heat_kw':self.measured_heat(now)[0],
            'comparison':dict(matched) if matched else {},
            'confidence':'Validated model; forecast uncertainty included' if ready and len(points)>=24 else 'Insufficient calibrated measurements',
            'billing_status':annual['status']}
