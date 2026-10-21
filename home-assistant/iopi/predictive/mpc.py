"""Constrained receding-horizon mixed-integer thermal MPC using SciPy/HiGHS.

The decision is fuel-input power, not measured burner output. Only a supervised
permission/setpoint recommendation can reach the existing HA control owner.
"""
import math
from datetime import datetime
from .telemetry import LOCAL
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix


def solve(indoor, forecast, model, config, tank_kwh=0, gas_allowed=None, previous_kw=0, initial_on=False):
    dt=0.25
    horizon=min(config.get('horizon_hours',48),len(forecast))
    n=int(horizon/dt)
    if n<96: return {'status':'fallback','reason':'At least 24 hours of hourly weather required','plan':[]}
    h,c=model['h_kw_k'],model['c_kwh_k']
    eta=config.get('efficiency')
    if not (0<h<=5 and 0<c<=200 and eta is not None and 0.5<=eta<=1.1):
        return {'status':'fallback','reason':'Thermal model / efficiency uncalibrated','plan':[]}
    weights=config['weights']
    # q fuel kW, room T, shortfall s, on u, starts z, variation v, tank draw r, tank E.
    offsets={}; size=0
    for name,count in [('q',n),('t',n+1),('s',n),('u',n),('z',n),('v',n),('r',n),('e',n+1),('w',n),('ws',n)]:
        offsets[name]=size; size+=count
    def ix(name,i): return offsets[name]+i
    objective=np.zeros(size); bounds=[(0,None)]*size; integer=np.zeros(size)
    eq=[]; eb=[]; ub=[]; rhs=[]
    def equality(row,b): eq.append(row); eb.append(b)
    def limit(row,b): ub.append(row); rhs.append(b)
    cap=config.get('max_fuel_kw',35); minimum=config.get('min_fuel_kw',3)
    comfort=config.get('comfort_c',18); safety=config.get('minimum_c',15)
    storage=bool(config.get('hydraulics_verified') and config.get('tank_average_verified') and tank_kwh>0)
    available=tank_kwh if storage else 0
    bounds[ix('t',0)]=(indoor,indoor); bounds[ix('e',0)]=(available,available)
    for i in range(n):
        p=forecast[min(len(forecast)-1,int(i*dt))]
        wind=max(0,p.wind_ms or 0)
        effective_h=h+wind*model.get('wind_h',0)
        a=math.exp(-effective_h*dt/c); b=(1-a)/effective_h
        solar=(p.solar_w_m2 or 0)/1000*max(0,model.get('solar_kw_per_kw_m2',0))
        internal=model.get('internal_kw',0)
        # Cold-side uncertainty margin, not an invented outdoor measurement.
        outside=p.temperature-config.get('risk_margin',0.5)*p.uncertainty_c
        equality({ix('t',i+1):1,ix('t',i):-a,ix('q',i):-b*eta,ix('r',i):-b},(1-a)*outside+b*(solar+internal))
        equality({ix('e',i+1):1,ix('e',i):-1,ix('r',i):dt},0)
        bounds[ix('t',i+1)]=(safety,config.get('maximum_c',24))
        bounds[ix('e',i+1)]=(0,available)
        bounds[ix('r',i)]=(0,config.get('max_transfer_kw',10) if storage else 0)
        for name in ('w','ws'):
            bounds[ix(name,i)]=(0,1 if storage else 0); integer[ix(name,i)]=1
        limit({ix('r',i):1,ix('w',i):-config.get('max_transfer_kw',10)},0)
        limit({ix('r',i):-1,ix('w',i):.2},0)
        storage_start={ix('w',i):1,ix('ws',i):-1}
        if i: storage_start[ix('w',i-1)]=-1
        limit(storage_start,0)
        allowed=gas_allowed[i] if gas_allowed is not None and i<len(gas_allowed) else True
        bounds[ix('q',i)]=(0,cap if allowed else 0)
        for name in ('u','z'):
            bounds[ix(name,i)]=(0,1); integer[ix(name,i)]=1
        limit({ix('q',i):1,ix('u',i):-cap},0)
        limit({ix('q',i):-1,ix('u',i):minimum},0)
        limit({ix('t',i+1):-1,ix('s',i):-1},-comfort)
        start={ix('u',i):1,ix('z',i):-1}
        if i: start[ix('u',i-1)]=-1
        limit(start,float(initial_on) if i==0 else 0)
        up={ix('q',i):1,ix('v',i):-1}; down={ix('q',i):-1,ix('v',i):-1}
        if i:
            up[ix('q',i-1)]=-1; down[ix('q',i-1)]=1
        limit(up,previous_kw if i==0 else 0); limit(down,-previous_kw if i==0 else 0)
        run=max(1,math.ceil(config.get('min_run_minutes',15)/15))
        rest=max(1,math.ceil(config.get('min_rest_minutes',10)/15))
        for j in range(i,min(n,i+run)):
            limit({ix('z',i):1,ix('u',j):-1},0)
            limit({ix('ws',i):1,ix('w',j):-1},0)
        # A 1->0 transition enforces minimum rest, except at horizon truncation.
        if i:
            for j in range(i,min(n,i+rest)):
                row={ix('u',i-1):1,ix('u',i):-1}
                row[ix('u',j)]=row.get(ix('u',j),0)+1
                limit(row,1)
                storage_rest={ix('w',i-1):1,ix('w',i):-1}
                storage_rest[ix('w',j)]=storage_rest.get(ix('w',j),0)+1
                limit(storage_rest,1)
        price=config.get('price_per_kwh')
        price=1 if price is None else max(0,price)
        objective[ix('q',i)]=dt*(weights['gas']*price+weights['annual_budget']*config.get('budget_pressure',0)
                                            +weights['forecast_risk']*p.uncertainty_c*0.01)
        objective[ix('s',i)]=weights['comfort']*dt
        objective[ix('z',i)]=weights['cycling']
        objective[ix('v',i)]=weights['variation']
        # Transfer is beneficial only if its avoided fuel exceeds electricity/loss cost.
        objective[ix('r',i)]=dt*(config.get('transfer_loss_fraction',0.05)*price+
            config.get('pump_kwh_per_heat_kwh',0.02)*config.get('electricity_price_per_kwh',1))
        objective[ix('w',i)]=dt*config.get('pump_electric_kw',.05)*config.get('electricity_price_per_kwh',1)
        objective[ix('ws',i)]=weights['cycling']
    # 5/7m³ preferences are soft, and only have meaning with valid billing conversion.
    factor=config.get('kwh_per_m3')
    if factor and factor>0:
        # Price marginal fuel above each daily preference using explicit slack variables.
        groups={}
        for i in range(n):
            day=datetime.fromtimestamp(forecast[0].at+i*900,LOCAL).date().isoformat()
            groups.setdefault(day,[]).append(i)
        old_size=size; size+=len(groups)*2
        objective=np.pad(objective,(0,size-old_size)); integer=np.pad(integer,(0,size-old_size))
        bounds.extend([(0,None)]*(size-old_size))
        for day,(date,indices) in enumerate(groups.items()):
            for k,preference in enumerate((config.get('preferred_daily_m3',5),config.get('soft_ceiling_m3',7))):
                slack=old_size+day*2+k
                row={ix('q',i):dt for i in indices}
                row[slack]=-1
                used=config.get('used_kwh_by_local_day',{}).get(date,0)
                limit(row,max(0,preference*factor-used))
                objective[slack]=weights['daily_preference']*(1+k)
    def matrix(rows):
        rr=[]; cc=[]; vv=[]
        for ri,row in enumerate(rows):
            for ci,v in row.items(): rr.append(ri); cc.append(ci); vv.append(v)
        return coo_matrix((vv,(rr,cc)),shape=(len(rows),size)).tocsr()
    try:
        result=linprog(objective,A_ub=matrix(ub),b_ub=np.array(rhs),A_eq=matrix(eq),b_eq=np.array(eb),
            bounds=bounds,integrality=integer,method='highs',options={'time_limit':config.get('solver_seconds',5),'mip_rel_gap':0.02})
        # A timed-out/inexact incumbent is not automatically authorised for control.
        if not result.success or result.x is None:
            return {'status':'fallback','reason':'Solver infeasible or timed out: '+str(result.message),'plan':[]}
        x=result.x
        if np.max(np.abs(matrix(eq)@x-np.array(eb)))>1e-5 or np.max(matrix(ub)@x-np.array(rhs))>1e-5:
            return {'status':'fallback','reason':'Solver constraint residual exceeded tolerance','plan':[]}
        plan=[{'at':forecast[0].at+i*900,'gas_input_kw':float(max(0,x[ix('q',i)])),
               'room_c':float(x[ix('t',i+1)]),'tank_transfer_kw':float(max(0,x[ix('r',i)])),
               'tank_kwh':float(max(0,x[ix('e',i+1)])),'quality':'model_estimated'} for i in range(n)]
        return {'status':'optimal','reason':'Constrained HiGHS MPC solution','objective':float(result.fun),
                'plan':plan,'fuel_kwh':sum(r['gas_input_kw']*dt for r in plan),'horizon_hours':horizon}
    except (ValueError,RuntimeError,TypeError) as exc:
        return {'status':'fallback','reason':'Solver failure: '+str(exc)[:160],'plan':[]}
