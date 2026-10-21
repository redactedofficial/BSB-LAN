"""Native Home Assistant panels: calm overview, progressively disclosed planning details."""
import json
import copy
from pathlib import Path

def heading(name,icon): return {'type':'heading','heading':name,'icon':icon}
def tile(entity,name,icon=None):
    row={'type':'tile','entity':entity,'name':name,'tap_action':{'action':'more-info'}}
    if icon: row['icon']=icon
    return row
def link(name,path,icon):
    return {'type':'button','name':name,'icon':icon,'tap_action':{'action':'navigate','navigation_path':path}}
def markdown(text): return {'type':'markdown','content':text}
def section(cards): return {'type':'grid','cards':cards}

REPORT="{% set r = 'sensor.bsb_predictive_report' %}"
SUMMARY=REPORT+"""
**{{ states('sensor.bmsiopi_heating_status') }}**

{% if states('select.bmsiopi_pump_control') == 'On' %}The radiator pump is held on manually. Calendars continue.
{% elif states('select.bmsiopi_pump_control') == 'Off' %}Room heating and the pump are held off. Any active pump run-on completes first. Calendars and hot water keep their own settings.
{% else %}{{ state_attr(r,'reason') or 'Waiting for a fresh heating decision.' }}{% endif %}

{% if state_attr(r,'actual_room_c') is number %}Room: **{{ state_attr(r,'actual_room_c') | round(1) }} °C measured**.
{% else %}Room temperature is unavailable. Delta demand and the existing controller remain in charge.{% endif %}
"""

def build(bms_source,iopi_source,outdir):
    out=Path(outdir)
    bms=json.loads(Path(bms_source).read_text(encoding='utf8'))['data']['config']
    iopi=json.loads(Path(iopi_source).read_text(encoding='utf8'))['data']['config']
    nav=[link('Heating plan','/bms-overview/heating-plan','mdi:chart-timeline-variant'),
         link('Gas & allowance','/bms-overview/gas-plan','mdi:meter-gas'),
         link('Diagnostics','/bms-overview/heating-diagnostics','mdi:stethoscope')]
    summary=section([heading('Heating now','mdi:home-thermometer'),markdown(SUMMARY),
        tile('sensor.bsb_optimizer_daily_total','Gas today · fuel estimate','mdi:meter-gas'),*nav])
    overview=bms['views'][0]
    primary_names={'Pump only',"Fuck, it's so cold",'Pump: Auto','Stop heating & pump'}
    primary=[copy.deepcopy(c) for s in overview.get('sections',[]) for c in s.get('cards',[])
             if c.get('name') in primary_names]
    # Reuse the exact established actions and boost confirmation at the top of the panel.
    if primary: summary['cards'][2:2]=primary
    overview['sections']=[s for s in overview.get('sections',[]) if not any(c.get('heading')=='Heating now' for c in s.get('cards',[]))]
    overview['sections'].insert(0,summary)
    def replace_legacy(value):
        if isinstance(value,dict):
            if value.get('entity')=='sensor.estimated_gas_today':
                value['entity']='sensor.bsb_optimizer_daily_total'; value['name']='Gas today · kWh estimate'
            if value.get('entity')=='sensor.estimated_gas_this_month':
                value['entity']='sensor.bsb_lan_estimated_gas_energy_this_month'; value['name']='This month · kWh estimate'
            if '9.66228' in value.get('content',''):
                value['content']='Boiler-estimated fuel energy. Billing volume requires the dated heating value and correction factor; no fixed kWh/m³ conversion is used in the new planner. [Gas & allowance](/bms-overview/gas-plan)'
            if 'Seasonal gas-budget limiter: not enabled' in value.get('content',''):
                value['content']='Production planning is integrated. Temperature optimization and annual costs require the measured inputs and billing data shown in [Heating plan](/bms-overview/heating-plan).'
            for child in value.values(): replace_legacy(child)
        elif isinstance(value,list):
            for child in value: replace_legacy(child)
    replace_legacy(overview)
    plan=REPORT+"""
{% set p = state_attr(r,'plan') or {} %}
{% if p.get('status') == 'optimal' %}
**{{ p.get('horizon_hours') }}-hour heating plan · model estimate**

Time | Room | Gas input
---|---:|---:
{% for row in p.get('plan',[])[::4] %}{{ row.at | timestamp_custom('%a %H:%M %Z') }} | {{ row.room_c | round(1) }} °C | {{ row.gas_input_kw | round(1) }} kW
{% endfor %}
{% else %}**A validated temperature plan is not available yet.**

{{ p.get('reason','Waiting for measurements and weather.') }} Existing heating and manual controls continue.{% endif %}
"""
    days=REPORT+"""
{% set rows = state_attr(r,'weather_days') or [] %}
{% if rows %}Day | Outside · forecast
---|---:
{% for row in rows %}{{ row.date }} | {{ row.outdoor_mean_c | round(1) }} °C
{% endfor %}
{% else %}Weather forecast unavailable. Scheduled Delta heating remains available.{% endif %}

Hourly coverage: **{{ state_attr(r,'hourly_forecast_hours') or 0 }} hours**. Missing hours are not invented. Seven-day gas demand needs calibrated daily history; forecast sunshine alone does not prove useful tank heat.
"""
    settings={'type':'entities','show_header_toggle':False,'entities':[
        {'entity':'input_select.bsb_optimizer_mode','name':'Control mode'},
        {'entity':'input_number.bsb_optimizer_comfort','name':'Planned room target'},
        {'entity':'input_number.bsb_optimizer_preferred','name':'Preferred gas / day'},
        {'entity':'input_number.bsb_optimizer_ceiling','name':'Soft ceiling / day'},
        {'entity':'input_number.bsb_optimizer_risk','name':'Forecast caution'}]}
    heatview={'title':'Heating plan','path':'heating-plan','type':'sections','max_columns':3,'icon':'mdi:chart-timeline-variant','sections':[
       section([heading('Heating decisions','mdi:brain'),markdown(SUMMARY),settings,
                markdown('Daily gas values are soft preferences. Essential heating can exceed them. Production adjusts automatic permissions only when measurements and calibration are valid. Manual controls and hot water keep their existing owners.'),
                link('Back to controls','/bms-overview/overview','mdi:arrow-left')]),
       section([heading('Next 24–48 hours','mdi:clock-outline'),markdown(plan),
          {'type':'history-graph','hours_to_show':24,'entities':[
             {'entity':'sensor.bsb_optimizer_predicted_room','name':'Predicted next room'},
             {'entity':'sensor.bsb_optimizer_actual_room','name':'Actual room · if available'}]}]),
       section([heading('Weather outlook','mdi:weather-partly-cloudy'),markdown(days),
          tile('sensor.bsb_optimizer_confidence','Forecast confidence'),
          markdown(REPORT+"**Tank:** {{ state_attr(r,'solar_evidence') or 'Source unconfirmed' }}. B3 is a single probe; usable tank energy remains unknown until representative sensors and the hydraulic path are verified.")]) ]}
    stop=next((c for c in primary if c.get('name')=='Stop heating & pump'),None)
    if stop: heatview['sections'][0]['cards'].insert(2,copy.deepcopy(stop))
    gas=REPORT+"""
{% set a = state_attr(r,'annual') or {} %}
**{{ a.get('status','Billing data not configured') }}**

{% if a.get('known_consumption_kwh') is number %}Known billing-period consumption: {{ a.known_consumption_kwh | round(1) }} kWh. Coverage: {{ (a.get('coverage',0)*100) | round(1) }}%.{% endif %}

Remaining allowance, year-end demand and cost stay unavailable when billing history, conversion factors, tariffs or seasonal calibration are missing. No MVM account connection is configured. Import invoices and verified tariff information using the documented billing file.

Fuel counters are boiler estimates. They do not measure delivered radiator heat. Cubic metres require the heating value and correction factor from the applicable bill. Unused allowance carries forward within the configured billing year; the controller never burns gas to use it up.
"""
    gasview={'title':'Gas & allowance','path':'gas-plan','type':'sections','max_columns':3,'icon':'mdi:meter-gas','sections':[
       section([heading('Today · fuel estimates','mdi:meter-gas'),
          *[tile('sensor.bsb_optimizer_'+key,name) for key,name in [('daily_total','Gas input today'),('daily_heating','Room heating'),('daily_dhw','Hot water'),('daily_m3','Billing volume · if configured')]],
          markdown(REPORT+"{% set d=state_attr(r,'daily') or {} %}Coverage today — total: {{ ((d.get('8380',{}).get('coverage',0))*100) | round(1) }}%; heating: {{ ((d.get('8378',{}).get('coverage',0))*100) | round(1) }}%; hot water: {{ ((d.get('8379',{}).get('coverage',0))*100) | round(1) }}%. Values with incomplete coverage are known partial consumption, not full-day totals."),
          link('Heating controls','/bms-overview/overview','mdi:arrow-left')]),
       section([heading('Annual plan · estimates','mdi:calendar-range'),markdown(gas),
          *[tile('sensor.bsb_optimizer_'+key,name) for key,name in [('annual_remaining','Remaining allowance'),('annual_projected','Projected annual consumption'),('annual_cost','Projected cost · currency in billing details')]]]),
       section([heading('Plan against actual','mdi:chart-line'),
          {'type':'history-graph','hours_to_show':48,'entities':[{'entity':'sensor.bsb_optimizer_matched_actual_fuel','name':'Actual interval fuel'}, {'entity':'sensor.bsb_optimizer_matched_predicted_fuel','name':'Predicted same interval'}]},
          markdown(REPORT+"{% set e=state_attr(r,'accuracy') or {} %}Matched 15-minute fuel error: {{ e.get('fuel',{}).get('rmse') if e.get('fuel',{}).get('rmse') is number else 'Unavailable' }} kWh. Matched samples: {{ e.get('fuel',{}).get('samples',0) }}. Comparison remains empty until a valid prediction has a later measured interval.")]) ]}
    diag=REPORT+"""
{% set rows=state_attr(r,'telemetry') or {} %}
Parameter | Value | Quality · acquired
---|---|---
{% for key,row in rows.items() %}{{ key }} | {{ row.value if row.value != none else 'Unavailable' }} {{ row.unit }} | {{ row.quality }} · {{ row.at | timestamp_custom('%H:%M:%S %Z') }}
{% endfor %}
"""
    diagview={'title':'Heating diagnostics','path':'heating-diagnostics','type':'sections','max_columns':3,'icon':'mdi:stethoscope','sections':[
       section([heading('Data & model readiness','mdi:stethoscope'),markdown(REPORT+"**{{ states(r) }}** — {{ state_attr(r,'reason') or 'No fresh report' }}\n\nMissing sensor parameters: {{ (state_attr(r,'missing_sensors') or []) | join(', ') }}.\n\nModel: {{ state_attr(r,'model') }}\n\nTank estimate: {{ state_attr(r,'tank') }}"),
          tile('sensor.bsb_optimizer_cycle_minutes','Average burner cycle · estimate'),tile('sensor.bsb_optimizer_model_rmse','Model fit error'),tile('sensor.bsb_optimizer_room_rmse','Matched room error'),
          link('Heating controls','/bms-overview/overview','mdi:arrow-left')]),
       section([heading('Timestamped telemetry','mdi:database-clock'),markdown(diag),
          markdown('Raw GPIO / relay drive indicates an electrical command, not measured circulation. Unknown physical sensor locations and missing flow remain unverified. Settings and rejection events are retained in the optimizer audit database and service journal.')]) ]}
    paths={'heating-plan','gas-plan','heating-diagnostics'}
    bms['views']=[v for v in bms['views'] if v.get('path') not in paths]+[heatview,gasview,diagview]
    # One link in the existing IO-PI overview; the BMS remains the planning owner.
    cards=iopi['views'][0]['sections'][0]['cards']
    if not any(c.get('name')=='Heating plan' for c in cards): cards.insert(1,nav[0])
    (out/'optimizer-bms.json').write_text(json.dumps(bms,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'optimizer-iopi.json').write_text(json.dumps(iopi,ensure_ascii=False,indent=2),encoding='utf8')
    return bms,iopi

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('--bms',required=True); p.add_argument('--iopi',required=True); p.add_argument('--out',required=True)
    a=p.parse_args(); build(a.bms,a.iopi,a.out)
