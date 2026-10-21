"""Validated, explicitly commissioned capabilities; unknown hardware stays unknown."""
import copy
from .telemetry import finite
from .budget import validate_billing

DEFAULT={
    'mode':'production','automatic_control_commissioned':False,'horizon_hours':48,
    'comfort_c':18,'minimum_c':15,'maximum_c':24,'efficiency':None,
    'max_fuel_kw':35,'min_fuel_kw':3,'min_run_minutes':15,'min_rest_minutes':10,
    'preferred_daily_m3':5,'soft_ceiling_m3':7,'solver_seconds':5,'risk_margin':0.5,
    'hydraulics_verified':False,'tank_average_verified':False,'flow_verified':False,
    'tank_volume_l':500,'tank_reference_c':30,'tank_sensor_keys':['8830'],
    'allow_estimated_heat_identification':False,'approved_model':None,
    'approved_water_curve':None,'external_sensors':{},'billing':{},
    'weights':{'gas':1,'comfort':150,'annual_budget':2,'cycling':0.2,
               'variation':0.03,'forecast_risk':1,'daily_preference':0.2}}

def validate(raw):
    if not isinstance(raw,dict): raise ValueError('Configuration must be an object')
    cfg=copy.deepcopy(DEFAULT); cfg.update(raw)
    if cfg['mode'] not in ('production','shadow','disabled'): raise ValueError('Invalid mode')
    for key in ('automatic_control_commissioned','hydraulics_verified','tank_average_verified',
                'flow_verified','allow_estimated_heat_identification'):
        if type(cfg[key]) is not bool: raise ValueError('Boolean required: '+key)
    ranges={'comfort_c':(12,23),'minimum_c':(5,18),'maximum_c':(18,28),
       'horizon_hours':(24,48),'max_fuel_kw':(1,100),'min_fuel_kw':(0,30),
       'min_run_minutes':(5,60),'min_rest_minutes':(5,60),'preferred_daily_m3':(0,50),
       'soft_ceiling_m3':(0,100),'solver_seconds':(1,15),'risk_margin':(0,2),
       'tank_volume_l':(1,10000),'tank_reference_c':(10,60)}
    for key,limits in {'max_transfer_kw':(0,100),'pump_electric_kw':(0,2),
          'electricity_price_per_kwh':(0,10000),'pump_kwh_per_heat_kwh':(0,1),
          'transfer_loss_fraction':(0,1)}.items():
        if key in cfg: ranges[key]=limits
    for key,(lo,hi) in ranges.items():
        cfg[key]=finite(cfg[key])
        if not lo<=cfg[key]<=hi: raise ValueError('Out of range: '+key)
    cfg['horizon_hours']=int(cfg['horizon_hours'])
    if not cfg['minimum_c']<cfg['comfort_c']<=cfg['maximum_c']: raise ValueError('Temperature ordering')
    if cfg['min_fuel_kw']>cfg['max_fuel_kw']: raise ValueError('Power ordering')
    if cfg['preferred_daily_m3']>cfg['soft_ceiling_m3']: raise ValueError('Daily preference ordering')
    if cfg['efficiency'] is not None and not 0.5<=finite(cfg['efficiency'])<=1.1: raise ValueError('Efficiency')
    for key in DEFAULT['weights']:
        if key not in cfg['weights'] or not 0<=finite(cfg['weights'][key])<=10000: raise ValueError('Weight '+key)
    if cfg['approved_model']:
        m=cfg['approved_model']
        if not m.get('calibration_source') or not 0.02<=finite(m['h_kw_k'])<=5 or not 0.5<=finite(m['c_kwh_k'])<=200:
            raise ValueError('Approved model requires bounded H, C and calibration source')
        for key,hi in [('wind_h',1),('internal_kw',20),('solar_kw_per_kw_m2',200)]:
            if not 0<=finite(m.get(key,0))<=hi: raise ValueError('Approved model '+key)
    if cfg['approved_water_curve']:
        c=cfg['approved_water_curve']
        if not c.get('commissioning_source') or not 30<=finite(c['return_at_0c'])<=55 or not 0<=finite(c['slope'])<=2:
            raise ValueError('Water curve needs commissioning record')
    for key,row in cfg['external_sensors'].items():
        if key not in ('room_actual','tank_top','tank_middle','tank_bottom','flow_m3h','supply_actual','return_actual','pump_feedback','delivered_kw'):
            raise ValueError('Unsupported external sensor '+key)
        if not row.get('topic','').startswith('bms/heating_sensors/') or not row.get('verified'):
            raise ValueError('External sensors need verified topic/physical identity')
        if not row.get('unit') or finite(row.get('minimum',-60))>=finite(row.get('maximum',140)):
            raise ValueError('External sensor unit/range')
        expected='m³/h' if key=='flow_m3h' else 'kW' if key=='delivered_kw' else 'binary' if key=='pump_feedback' else '°C'
        if row['unit']!=expected: raise ValueError('Physical unit required for '+key+': '+expected)
    if cfg['tank_average_verified'] and (len(cfg['tank_sensor_keys'])<2 or not cfg.get('tank_calibration_source')):
        raise ValueError('Tank average requires multiple identified sensors and calibration source')
    if cfg['flow_verified'] and not all(k in cfg['external_sensors'] for k in ('flow_m3h','supply_actual','return_actual')):
        raise ValueError('Verified flow needs identified flow and supply/return sensors')
    cfg['billing']=validate_billing(cfg['billing'])
    return cfg
