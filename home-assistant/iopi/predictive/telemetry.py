"""Typed observations and UTC interval accounting. No actuator interface."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

UTC = timezone.utc
LOCAL = ZoneInfo('Europe/Budapest')
# category, engineering unit, provenance. Do not include duplicate 8381..8383.
PARAMETERS = {
    8310:(36,'°C','measured'),8314:(36,'°C','measured'),8830:(37,'°C','measured'),
    8950:(37,'°C','unverified_location'),8378:(36,'kWh','controller_estimated'),
    8379:(36,'kWh','controller_estimated'),8380:(36,'kWh','controller_estimated'),
    8330:(36,'h','controller_counter'),8331:(36,'count','controller_counter'),
    8338:(36,'h','controller_counter'),8339:(36,'h','controller_counter'),
    8316:(36,'°C','measured'),8323:(36,'rpm','measured'),9005:(37,'bar','measured'),
    8009:(34,'enum','controller_state'),8005:(34,'enum','controller_state'),
    8000:(34,'enum','controller_state'),8003:(34,'enum','controller_state'),
    8304:(36,'enum','controller_state'),8730:(37,'enum','controller_state'),
    8820:(37,'enum','controller_state'),6700:(31,'enum','controller_state'),
    8740:(37,'°C','measured'),8700:(37,'°C','measured'),
    8980:(37,'°C','measured'),8983:(37,'°C','measured'),8982:(37,'°C','measured'),
    8510:(36,'°C','measured'),8519:(36,'°C','measured'),8520:(36,'°C','measured')}
TOPICS = {f'BSB-LAN/0/{row[0]}/{p}/status': str(p) for p,row in PARAMETERS.items()}


def finite(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a measurement')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite measurement')
    return result


def utc_timestamp(value):
    if isinstance(value, (float,int)):
        return finite(value)
    dt = datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timestamp requires an explicit offset')
    return dt.timestamp()


def local_day_bounds(day):
    day = datetime.fromisoformat(str(day)).date()
    start = datetime.combine(day, datetime.min.time(), LOCAL)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), LOCAL)
    return start.timestamp(), end.timestamp()


@dataclass
class Reading:
    value: float | str | None
    at: float
    unit: str
    quality: str

    def fresh(self, now, max_age=180):
        return self.value is not None and 0 <= now-self.at <= max_age


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=10000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS observations(key TEXT,at REAL,value TEXT,unit TEXT,quality TEXT,PRIMARY KEY(key,at));
        CREATE TABLE IF NOT EXISTS baselines(key TEXT PRIMARY KEY,at REAL,value REAL,unit TEXT);
        CREATE TABLE IF NOT EXISTS intervals(key TEXT,start REAL,end REAL,energy REAL,quality TEXT,PRIMARY KEY(key,start,end));
        CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS events(at REAL,kind TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS plans(slot INTEGER PRIMARY KEY,at REAL,result TEXT);
        CREATE TABLE IF NOT EXISTS predictions(issued REAL,target REAL,kind TEXT,value REAL,actual REAL,PRIMARY KEY(issued,target,kind));
        CREATE TABLE IF NOT EXISTS bills(id TEXT PRIMARY KEY,start REAL,end REAL,energy REAL,source TEXT);
        CREATE INDEX IF NOT EXISTS prediction_pending ON predictions(actual,target);
        CREATE INDEX IF NOT EXISTS prediction_accuracy ON predictions(kind,issued);
        ''')
        self.db.commit()

    def close(self): self.db.close()

    def event(self, at, kind, detail):
        self.db.execute('INSERT INTO events VALUES(?,?,?)',(at,kind,str(detail)[:500]))
        self.db.commit()

    def set_state(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO state VALUES(?,?)',(key,json.dumps(value,allow_nan=False)))
        self.db.commit()

    def get_state(self, key, default=None):
        row=self.db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def record(self, key, reading):
        self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?)',
                        (key,reading.at,json.dumps(reading.value),reading.unit,reading.quality))
        self.db.commit()

    def counter(self, key, at, value, unit='kWh', max_kw=100):
        if key not in ('8378','8379','8380') or unit not in ('kWh','MJ'):
            raise ValueError('Only canonical fuel counters with energy units are accepted')
        at,value=finite(at),finite(value)
        if value < 0: raise ValueError('Negative counter')
        value *= 1/3.6 if unit=='MJ' else 1
        previous=self.db.execute('SELECT * FROM baselines WHERE key=?',(key,)).fetchone()
        if previous and at <= previous['at']:
            return 'out_of_order'
        result='baseline'
        if previous:
            delta,elapsed=value-previous['value'],at-previous['at']
            if delta < -1e-6:
                result='reset'
                self.event(at,'counter_reset',key)
            elif delta > max_kw*elapsed/3600+1.0:
                # Do not poison the baseline with an implausible upward spike.
                self.event(at,'counter_spike',key)
                return 'spike'
            else:
                self.db.execute('INSERT OR IGNORE INTO intervals VALUES(?,?,?,?,?)',
                    (key,previous['at'],at,max(0,delta),'controller_estimated' if elapsed<=3600 else 'gap_interpolated'))
                result='delta'
        self.db.execute('INSERT OR REPLACE INTO baselines VALUES(?,?,?,?)',(key,at,value,'kWh'))
        self.db.commit()
        return result

    def energy(self, key, start, end):
        rows=self.db.execute('SELECT * FROM intervals WHERE key=? AND end>? AND start<?',(key,start,end)).fetchall()
        total=covered=0.0
        for row in rows:
            seconds=max(0,min(end,row['end'])-max(start,row['start']))
            total+=row['energy']*seconds/(row['end']-row['start'])
            covered+=seconds
        return {'kwh':total if rows else None,'coverage':min(1,covered/max(1,end-start)),
                'quality':'controller_estimated; boundary allocation uses elapsed seconds'}

    def today(self, now, key='8380'):
        day=datetime.fromtimestamp(now,LOCAL).date()
        start,end=local_day_bounds(day.isoformat())
        return self.energy(key,start,min(now,end))

    def prune(self, now, days=400):
        cut=now-days*86400
        # Raw observations bounded to 35 days; energy intervals/billing retained for annual planning.
        self.db.execute('DELETE FROM observations WHERE at<?',(now-35*86400,))
        self.db.execute('DELETE FROM events WHERE at<?',(cut,))
        self.db.execute('DELETE FROM plans WHERE at<?',(cut,))
        self.db.execute('DELETE FROM predictions WHERE issued<?',(cut,))
        self.db.commit()


class Telemetry:
    def __init__(self, store):
        self.store,self.readings=store,{}

    def ingest(self, key, payload, at, unit=None, quality=None):
        if key in ('8381','8382','8383'): return False
        if key.isdigit() and int(key) in PARAMETERS:
            _,expected,provenance=PARAMETERS[int(key)]
            if unit is not None and unit != expected:
                raise ValueError('Unit mismatch for '+key)
            unit,quality=expected,quality or provenance
            try:
                value=finite(str(payload).split(' - ',1)[0])
                if unit=='°C' and not -60<=value<=140: raise ValueError('Temperature range')
                if unit in ('kWh','count','h','bar','rpm') and value<0: raise ValueError('Negative measurement')
            except (ValueError,TypeError): value=None
        else:
            unit,quality=unit or 'state',quality or 'controller_state'
            value=payload
        old=self.readings.get(key)
        if old and at<=old.at: return False
        reading=Reading(value,at,unit,quality)
        self.readings[key]=reading
        self.store.record(key,reading)
        if key in ('8378','8379','8380') and value is not None:
            self.store.counter(key,at,value,unit)
        return True

    def value(self, key, now, age=180):
        reading=self.readings.get(key)
        return reading.value if reading and reading.fresh(now,age) else None

    def report(self, now):
        return {k:{'value':r.value if r.fresh(now) else None,'at':r.at,'unit':r.unit,
                   'quality':r.quality,'fresh':r.fresh(now)} for k,r in self.readings.items()}
