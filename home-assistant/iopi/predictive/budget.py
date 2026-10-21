"""Annual billing ledger, configurable verified tariffs and seasonal forecasting."""
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
from .telemetry import LOCAL, finite, utc_timestamp


def energy_kwh(value, unit, heating_value_mj_m3=None, correction=None):
    value=finite(value)
    if value<0: raise ValueError('Negative billed energy')
    if unit=='kWh': return value
    if unit=='MJ': return value/3.6
    if unit=='m3':
        if heating_value_mj_m3 is None or correction is None:
            raise ValueError('Volume conversion needs billing heating value AND correction factor')
        hv,corr=finite(heating_value_mj_m3),finite(correction)
        if not 20<=hv<=50 or not 0.8<=corr<=1.2: raise ValueError('Invalid billing conversion')
        return value*hv*corr/3.6
    raise ValueError('Unsupported billing unit')


def validate_billing(config):
    if not config: return {}
    result=dict(config)
    if config.get('allowance') is not None:
        energy_kwh(config['allowance'],config.get('allowance_unit','kWh'),config.get('allowance_heating_value_mj_m3'),config.get('allowance_correction'))
    if config.get('year_start') is not None:
        start=date.fromisoformat(config['year_start']); end=date.fromisoformat(config['year_end'])
        if not 300<=(end-start).days<=400: raise ValueError('Billing period must describe one annual cycle')
    conversions=[]
    for row in config.get('conversions',[]):
        if utc_timestamp(row['end'])<=utc_timestamp(row['start']): raise ValueError('Conversion dates')
        energy_kwh(1,'m3',row['heating_value_mj_m3'],row['correction'])
        a,b=utc_timestamp(row['start']),utc_timestamp(row['end'])
        if any(x<b and y>a for x,y in conversions): raise ValueError('Overlapping billing conversions')
        conversions.append((a,b))
    previous=-1; unlimited=False; currencies=set()
    for row in config.get('tariffs',[]):
        if not row.get('verified_source') or not row.get('currency'):
            raise ValueError('Tariff needs a verified source and currency')
        if finite(row['price_per_kwh'])<0: raise ValueError('Negative tariff')
        if row.get('up_to_kwh') is not None and finite(row['up_to_kwh'])<0: raise ValueError('Tariff band')
        ceiling=math.inf if row.get('up_to_kwh') is None else finite(row['up_to_kwh'])
        if unlimited or ceiling<=previous: raise ValueError('Tariff bands must increase; unlimited band last')
        previous=ceiling; unlimited=math.isinf(ceiling); currencies.add(row['currency'])
    if len(currencies)>1: raise ValueError('Mixed tariff currencies')
    allocations=config.get('seasonal_allocations',[])
    if allocations and (len(allocations)!=12 or min(allocations)<0 or abs(sum(allocations)-1)>1e-6):
        raise ValueError('Configured seasonal allocations must be 12 fractions summing to one')
    climate=config.get('monthly_outdoor_normals_c')
    if climate and (len(climate)!=12 or any(not -60<=finite(v)<=60 for v in climate)):
        raise ValueError('Twelve bounded monthly climate normals required')
    return result


def conversion_at(config, at):
    matches=[r for r in config.get('conversions',[]) if utc_timestamp(r['start'])<=at<utc_timestamp(r['end'])]
    if len(matches)!=1: return None
    row=matches[0]
    return energy_kwh(1,'m3',row['heating_value_mj_m3'],row['correction'])


def volume_between(store, config, start, end):
    rows=store.db.execute('SELECT * FROM intervals WHERE key="8380" AND end>? AND start<?',(start,end)).fetchall()
    if not rows: return None
    total=0
    for row in rows:
        a,b=max(start,row['start']),min(end,row['end'])
        boundaries=sorted({a,b,*[utc_timestamp(c[k]) for c in config.get('conversions',[]) for k in ('start','end')
                                  if a<utc_timestamp(c[k])<b]})
        for left,right in zip(boundaries,boundaries[1:]):
            factor=conversion_at(config,(left+right)/2)
            if factor is None: return None
            total+=row['energy']*(right-left)/(row['end']-row['start'])/factor
    return total


def import_bills(store, rows):
    if not isinstance(rows,list): raise ValueError('Bills must be a list')
    prepared=[]
    for row in rows:
        start,end=utc_timestamp(row['start']),utc_timestamp(row['end'])
        if end<=start or not row.get('id') or not row.get('source'): raise ValueError('Incomplete bill')
        energy=energy_kwh(row['consumption'],row['unit'],row.get('heating_value_mj_m3'),row.get('correction'))
        for old in store.db.execute('SELECT * FROM bills WHERE id!=? AND start<? AND end>?',(row['id'],end,start)):
            raise ValueError('Overlapping authoritative billing imports')
        if any(x[0]!=row['id'] and x[1]<end and x[2]>start for x in prepared): raise ValueError('Overlapping bills')
        prepared.append((str(row['id']),start,end,energy,str(row['source'])))
    with store.db:
        store.db.executemany('INSERT OR REPLACE INTO bills VALUES(?,?,?,?,?)',prepared)
    return len(prepared)


def actual_annual(store, start, end):
    bills=store.db.execute('SELECT * FROM bills WHERE end>? AND start<? ORDER BY start',(start,end)).fetchall()
    intervals=store.db.execute('SELECT * FROM intervals WHERE key="8380" AND end>? AND start<? ORDER BY start',(start,end)).fetchall()
    boundaries=sorted({start,end,*[max(start,r['start']) for r in [*bills,*intervals]],
                               *[min(end,r['end']) for r in [*bills,*intervals]]})
    energy=covered=0
    bi=ci=0
    for a,b in zip(boundaries,boundaries[1:]):
        while bi<len(bills) and bills[bi]['end']<=a: bi+=1
        while ci<len(intervals) and intervals[ci]['end']<=a: ci+=1
        row=None
        if bi<len(bills) and bills[bi]['start']<=a and bills[bi]['end']>=b: row=bills[bi]
        elif ci<len(intervals) and intervals[ci]['start']<=a and intervals[ci]['end']>=b: row=intervals[ci]
        if row is not None:
            energy+=row['energy']*(b-a)/(row['end']-row['start']); covered+=b-a
    return {'known_kwh':energy,'coverage':covered/max(1,end-start),
            'quality':'billing imports plus nonoverlapping controller estimates; partial boundaries interpolated'}


def tariff_cost(kwh, config):
    bands=config.get('tariffs',[])
    if not bands: return None
    if len({r['currency'] for r in bands})!=1: raise ValueError('Mixed tariff currencies')
    cost=previous=0.0
    for band in bands:
        ceiling=band.get('up_to_kwh')
        upper=math.inf if ceiling is None else finite(ceiling)
        if upper<=previous: raise ValueError('Unordered tariff bands')
        cost+=max(0,min(kwh,upper)-previous)*finite(band['price_per_kwh'])
        if kwh<=upper: return cost
        previous=upper
    return None


class AnnualPlanner:
    def __init__(self, store, config): self.store,self.config=store,validate_billing(config)

    def forecast(self, now, weather_days, heating_daily=None, dhw_daily=None, comfort=18):
        cfg=self.config
        slope=heating_daily.get('kwh_per_degree_day') if heating_daily else None
        baseline=dhw_daily
        seven=[]
        for row in weather_days:
            need=(max(0,comfort-row['outdoor_mean_c'])*slope+baseline if slope is not None and baseline is not None else None)
            seven.append(dict(row,gas_kwh=need,quality='weather_regression_estimate' if need is not None else 'unavailable'))
        if not cfg.get('year_start') or cfg.get('allowance') is None:
            return {'status':'Billing year / annual allowance required','remaining_kwh':None,
                    'projected_kwh':None,'cost':None,'quality':'unavailable','soft_preferences_m3':[5,7],'seven_days':seven}
        start=datetime.combine(date.fromisoformat(cfg['year_start']),datetime.min.time(),LOCAL).timestamp()
        end=datetime.combine(date.fromisoformat(cfg['year_end']),datetime.min.time(),LOCAL).timestamp()
        if not start<=now<end: return {'status':'Configured billing year does not include today','remaining_kwh':None,'projected_kwh':None,'cost':None}
        allowance=energy_kwh(cfg['allowance'],cfg.get('allowance_unit','kWh'),cfg.get('allowance_heating_value_mj_m3'),cfg.get('allowance_correction'))
        actual=actual_annual(self.store,start,now)
        # Missing historical consumption must not be silently interpreted as zero.
        complete=actual['coverage']>=0.98
        remaining=allowance-actual['known_kwh'] if complete else None
        forecast_remaining=None
        # Long-range temperatures are explicit configurable climatology, never fabricated forecasts.
        climate=cfg.get('monthly_outdoor_normals_c')
        if slope is not None and baseline is not None and climate and len(climate)==12:
            forecast_remaining=0.0; day=datetime.fromtimestamp(now,LOCAL).date(); final=date.fromisoformat(cfg['year_end'])
            by_day={r['date']:r['outdoor_mean_c'] for r in weather_days}
            while day<final:
                a=datetime.combine(day,datetime.min.time(),LOCAL).timestamp()
                b=datetime.combine(day+timedelta(days=1),datetime.min.time(),LOCAL).timestamp()
                fraction=max(0,b-max(a,now))/(b-a)
                temp=by_day.get(day.isoformat(),finite(climate[day.month-1]))
                forecast_remaining+=fraction*(max(0,comfort-temp)*slope+baseline)
                day+=timedelta(days=1)
        projected=actual['known_kwh']+forecast_remaining if complete and forecast_remaining is not None else None
        return {'status':'Ready' if projected is not None else 'Consumption coverage / seasonal calibration incomplete',
                'known_consumption_kwh':actual['known_kwh'],'coverage':actual['coverage'],
                'remaining_kwh':remaining,'projected_kwh':projected,'allowance_kwh':allowance,
                'cost':tariff_cost(projected,cfg) if projected is not None else None,
                'currency':cfg.get('tariffs',[{}])[0].get('currency') if cfg.get('tariffs') else None,
                'seven_days':seven,'quality':'model_estimated','forecast_remaining_kwh':forecast_remaining,
                'configured_seasonal_allocations':cfg.get('seasonal_allocations',[])}
