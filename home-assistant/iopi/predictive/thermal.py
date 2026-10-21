"""Physical RC model, guarded online identification and thermal-storage estimates."""
import math
import numpy as np
from .telemetry import finite


def step_temperature(indoor, outdoor, heating_kw, solar_kw, internal_kw, h_kw_k, c_kwh_k, hours, wind_ms=0, wind_h=0):
    if c_kwh_k<=0 or h_kw_k<0 or not 0<hours<=2: raise ValueError('Invalid thermal model')
    h=h_kw_k+max(0,wind_ms)*max(0,wind_h)
    if h==0: return indoor+(heating_kw+solar_kw+internal_kw)*hours/c_kwh_k
    a=math.exp(-h*hours/c_kwh_k)
    return a*indoor+(1-a)*(outdoor+(heating_kw+solar_kw+internal_kw)/h)


def tank_energy(volume_l, temperatures, reference_c, verified_average=False, weights=None):
    if not 1<=volume_l<=10000 or not -10<=reference_c<=100: raise ValueError('Invalid tank configuration')
    good=[finite(t) for t in temperatures if t is not None]
    if len(good)!=len(temperatures) or not good or any(not 0<=t<=100 for t in good):
        return {'useful_kwh':None,'quality':'unavailable','reason':'Missing tank temperatures'}
    if not verified_average:
        return {'useful_kwh':None,'quality':'single_probe' if len(good)==1 else 'unverified_sensor_positions',
                'reason':'Representative tank average not established','probe_c':good}
    weights=weights or [1/len(good)]*len(good)
    if len(weights)!=len(good) or min(weights)<0 or abs(sum(weights)-1)>1e-6:
        raise ValueError('Tank weights must sum to one')
    average=sum(t*w for t,w in zip(good,weights))
    return {'useful_kwh':0.001163*volume_l*max(0,average-reference_c),
            'average_c':average,'quality':'model_estimated','reason':'Weighted, verified sensor positions; water approximation'}


def delivered_power(flow_m3h, supply_c, return_c, verified=False, water=True):
    if not verified or not water or None in (flow_m3h,supply_c,return_c): return None
    flow_m3h,supply_c,return_c=map(finite,(flow_m3h,supply_c,return_c))
    if not 0<=flow_m3h<=20 or not -30<=supply_c-return_c<=80: return None
    return 1.163*flow_m3h*(supply_c-return_c)


class Identification:
    """RLS for dT/dt = -a ΔT + b Q + s irradiance + g - w wind ΔT.

    Identification is disabled without actual room observations and verified heat
    input (or explicitly accepted estimated heat). Never learn from a room setpoint.
    """
    def __init__(self, saved=None):
        s=saved or {}
        self.theta=np.array(s.get('theta',[0.02,0.1,0.0,0.0,0.0]),dtype=float)
        self.p=np.array(s.get('p',np.eye(5)*10),dtype=float)
        self.gram=np.array(s.get('gram',np.zeros((5,5))),dtype=float)
        self.n=int(s.get('n',0)); self.squared_error=float(s.get('squared_error',0))

    def update(self, before, after, outdoor, heat_kw, hours, solar_w_m2=0, wind_ms=0, trusted=False):
        if not trusted or heat_kw is None or not 1/12<=hours<=1:
            return False
        values=list(map(finite,(before,after,outdoor,heat_kw,solar_w_m2,wind_ms)))
        before,after,outdoor,heat_kw,solar_w_m2,wind_ms=values
        if abs(after-before)>5 or not -10<=heat_kw<=60: return False
        x=np.array([-(before-outdoor),heat_kw,solar_w_m2/1000,1,-max(0,wind_ms)*(before-outdoor)])
        y=(after-before)/hours
        residual=y-float(x@self.theta)
        # Bounded innovations and forgetting prevent a single sensor step dominating calibration.
        residual=float(np.clip(residual,-3,3))
        forgetting=0.995
        gain=self.p@x/(forgetting+x@self.p@x)
        self.theta+=gain*residual
        self.theta[0]=np.clip(self.theta[0],0.0002,0.5)
        self.theta[1]=np.clip(self.theta[1],0.002,2)
        self.theta[2]=np.clip(self.theta[2],0,20)
        self.theta[3]=np.clip(self.theta[3],-0.5,2)
        self.theta[4]=np.clip(self.theta[4],0,0.1)
        self.p=(self.p-np.outer(gain,x)@self.p)/forgetting
        self.p=(self.p+self.p.T)/2
        self.gram+=np.outer(x,x)
        self.n+=1; self.squared_error+=residual**2
        return True

    def parameters(self):
        c=1/self.theta[1]; h=self.theta[0]*c
        excitation=np.linalg.eigvalsh(self.gram[np.ix_([0,1],[0,1])])
        ready=self.n>=72 and min(excitation)>10 and 0.02<=h<=5 and 0.5<=c<=200 and self.rmse<0.75
        return {'h_kw_k':float(h),'c_kwh_k':float(c),'solar_kw_per_kw_m2':float(self.theta[2]*c),
                'internal_kw':float(self.theta[3]*c),'wind_h':float(self.theta[4]*c),
                'calibrated':bool(ready),'samples':self.n,'rmse_c_per_hour':self.rmse,
                'quality':'model_estimated','covariance_diagonal':np.diag(self.p).tolist()}

    @property
    def rmse(self): return math.sqrt(self.squared_error/self.n) if self.n else None

    def state(self):
        return {'theta':self.theta.tolist(),'p':self.p.tolist(),'gram':self.gram.tolist(),
                'n':self.n,'squared_error':self.squared_error}


def cycling(hours_delta, starts_delta):
    if hours_delta is None or starts_delta is None or hours_delta<0 or starts_delta<=0:
        return {'average_cycle_minutes':None,'short_cycling':None}
    minutes=60*hours_delta/starts_delta
    return {'average_cycle_minutes':minutes,'short_cycling':minutes<5,
            'quality':'controller_estimated; coarse runtime counter resolution'}
