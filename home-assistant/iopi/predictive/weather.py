"""Use the existing HA weather provider. Never fabricate a missing forecast."""
from dataclasses import dataclass
from datetime import datetime
from .telemetry import LOCAL, finite, utc_timestamp


@dataclass
class WeatherPoint:
    at: float
    temperature: float
    wind_ms: float | None = None
    solar_w_m2: float | None = None
    clouds: float | None = None
    uncertainty_c: float = 2


class Forecast:
    def __init__(self, payload, now):
        if payload.get('temperature_unit')!='°C': raise ValueError('Forecast needs Celsius')
        self.generated=utc_timestamp(payload['generated_at'])
        if not -60<=now-self.generated<=7200: raise ValueError('Stale/future forecast')
        self.source=str(payload.get('source','Home Assistant weather'))[:80]
        self.current=payload.get('current_temperature')
        if self.current is not None: self.current=finite(self.current)
        if self.current is not None and not -60<=self.current<=60: raise ValueError('Current weather range')
        wind_unit=payload.get('wind_speed_unit','km/h')
        factors={'km/h':1/3.6,'m/s':1,'mph':0.44704,'kn':0.514444}
        self.points=[]; seen=set()
        for row in payload.get('hourly',[])[:400]:
            at=utc_timestamp(row['datetime'])
            if at in seen or not now-3600<=at<=now+14*86400: continue
            temp=finite(row['temperature'])
            if not -60<=temp<=60: continue
            seen.add(at)
            wind=row.get('wind_speed'); radiation=row.get('solar_radiation')
            if wind is not None and wind_unit in factors and not 0<=finite(wind)*factors[wind_unit]<=100:
                raise ValueError('Wind range')
            if radiation is not None and not 0<=finite(radiation)<=1500: raise ValueError('Solar radiation range')
            if row.get('cloud_coverage') is not None and not 0<=finite(row['cloud_coverage'])<=100:
                raise ValueError('Cloud cover range')
            self.points.append(WeatherPoint(at,temp,
                finite(wind)*factors[wind_unit] if wind is not None and wind_unit in factors else None,
                finite(radiation) if radiation is not None else None,
                finite(row['cloud_coverage']) if row.get('cloud_coverage') is not None else None,
                min(8,1.5+max(0,at-now)/86400*0.7)))
        self.points.sort(key=lambda p:p.at)
        self.daily=payload.get('daily',[])[:14]

    def horizon(self, now, hours=48):
        result=[]
        for i in range(hours):
            at=now+i*3600
            if not self.points or at>=self.points[-1].at+3600: break
            candidates=[p for p in self.points if p.at<=at+900 and at-p.at<=5400]
            if not candidates:
                # HA often starts its hourly series at the next hour. Use the provider's
                # current estimate for this partial hour, never an invented future point.
                if i==0 and self.current is not None and 0<self.points[0].at-now<=3600:
                    result.append(WeatherPoint(at,self.current,uncertainty_c=2)); continue
                break
            source=candidates[-1]
            result.append(WeatherPoint(at,source.temperature,source.wind_ms,source.solar_w_m2,source.clouds,source.uncertainty_c))
        return result

    def seven_days(self, now):
        groups={}
        for p in self.points:
            day=datetime.fromtimestamp(p.at,LOCAL).date().isoformat()
            groups.setdefault(day,[]).append(p.temperature)
        for row in self.daily:
            day=datetime.fromtimestamp(utc_timestamp(row['datetime']),LOCAL).date().isoformat()
            if day not in groups and row.get('temperature') is not None:
                hi=finite(row['temperature']); lo=finite(row.get('templow',hi))
                if not -60<=lo<=hi<=60: raise ValueError('Daily forecast range')
                groups[day]=[(lo+hi)/2]
        today=datetime.fromtimestamp(now,LOCAL).date().isoformat()
        return [{'date':day,'outdoor_mean_c':sum(v)/len(v),'source':self.source,
                 'resolution':'hourly' if len(v)>1 else 'daily mean estimate'}
                for day,v in sorted(groups.items()) if day>=today][:7]
