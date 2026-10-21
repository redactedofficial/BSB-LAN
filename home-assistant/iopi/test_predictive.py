import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from predictive.config import validate, DEFAULT
from predictive.telemetry import Store, Telemetry, Reading, local_day_bounds, utc_timestamp
from predictive.thermal import step_temperature,tank_energy,delivered_power,Identification,cycling
from predictive.weather import Forecast, WeatherPoint
from predictive.budget import energy_kwh,import_bills,actual_annual,AnnualPlanner,volume_between,tariff_cost
from predictive.mpc import solve
from predictive.supervisor import SafetySupervisor,ProductionPublisher,SimulationPublisher
from predictive.engine import Engine
from optimizer_tools import backtest

NOW=datetime(2026,10,21,10,tzinfo=timezone.utc).timestamp()

def weather(now=NOW,temp=5,hours=48):
    return [WeatherPoint(now+i*3600,temp,2,0,20,2) for i in range(hours)]

class PredictiveTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:'); self.t=Telemetry(self.store); self.cfg=validate({'automatic_control_commissioned':True})
    def tearDown(self): self.store.close()
    def test_exact_model_balance(self):
        self.assertAlmostEqual(step_temperature(18,8,2,0,0,.2,10,1),18)
        self.assertLess(step_temperature(18,0,0,0,0,.2,10,1),18)
        self.assertGreater(step_temperature(18,8,3,1,0,.2,10,1),18)
    def test_tank_not_uniform_from_b3(self):
        self.assertIsNone(tank_energy(500,[50],30)['useful_kwh'])
        self.assertAlmostEqual(tank_energy(500,[60,50,40],30,True)['useful_kwh'],11.63)
    def test_flow_is_required_for_delivered_heat(self):
        self.assertIsNone(delivered_power(None,60,40,True))
        self.assertIsNone(delivered_power(1,60,40,False))
        self.assertAlmostEqual(delivered_power(1,60,40,True),23.26)
    def test_identification_needs_trusted_heat_and_excitation(self):
        m=Identification()
        self.assertFalse(m.update(18,18,5,None,.25))
        self.assertFalse(m.parameters()['calibrated'])
        for i in range(100): m.update(18,18,5,0,.25,trusted=True)
        self.assertFalse(m.parameters()['calibrated'])
        saved=Identification(m.state()); self.assertEqual(saved.n,100)
    def test_counter_resets_and_duplicates(self):
        self.t.ingest('8380','100',NOW)
        self.t.ingest('8380','101',NOW+3600)
        self.t.ingest('8381','99999',NOW+3600)
        self.t.ingest('8380','2',NOW+7200)
        self.t.ingest('8380','3',NOW+10800)
        self.assertEqual(self.store.energy('8380',NOW,NOW+10800)['kwh'],2)
        self.assertFalse(self.t.ingest('8380','999',NOW+3600))
    def test_counter_quantization_and_invalid_spike(self):
        self.store.counter('8380',NOW,100)
        self.assertEqual(self.store.counter('8380',NOW+15,101),'delta')
        self.assertEqual(self.store.counter('8380',NOW+30,9999),'spike')
        self.assertEqual(self.store.counter('8380',NOW+45,101),'delta')
    def test_restart_baseline_and_replay(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'db'; a=Store(str(p)); a.counter('8380',NOW,10); a.close()
            a=Store(str(p)); self.assertEqual(a.counter('8380',NOW,10),'out_of_order')
            a.counter('8380',NOW+3600,12)
            self.assertEqual(a.energy('8380',NOW,NOW+3600)['kwh'],2); a.close()
    def test_unit_stale_and_invalid_measurement(self):
        with self.assertRaises(ValueError): self.t.ingest('8314',40,NOW,'bar')
        self.t.ingest('8314','---',NOW); self.assertIsNone(self.t.value('8314',NOW))
        self.t.ingest('8314','40',NOW+1); self.assertIsNone(self.t.value('8314',NOW+200))
    def test_dst_and_gregorian_leap(self):
        self.assertEqual(local_day_bounds('2026-03-29')[1]-local_day_bounds('2026-03-29')[0],23*3600)
        self.assertEqual(local_day_bounds('2026-10-25')[1]-local_day_bounds('2026-10-25')[0],25*3600)
        self.assertEqual(local_day_bounds('2000-02-29')[1]-local_day_bounds('2000-02-29')[0],86400)
        with self.assertRaises(ValueError): local_day_bounds('2100-02-29')
        self.assertNotEqual(utc_timestamp('2026-10-25T02:15:00+02:00'),utc_timestamp('2026-10-25T02:15:00+01:00'))
        with self.assertRaises(ValueError): utc_timestamp('2026-10-25T02:15:00')
    def test_dst_energy_elapsed_seconds(self):
        a,b=local_day_bounds('2026-10-25')
        self.store.counter('8380',a,0); self.store.counter('8380',b,25)
        self.assertEqual(self.store.energy('8380',a,b)['kwh'],25)
        self.assertEqual(self.store.energy('8380',a,a+3600)['kwh'],1)
    def test_billing_conversion_and_overlap(self):
        with self.assertRaises(ValueError): energy_kwh(1,'m3')
        self.assertEqual(energy_kwh(36,'MJ'),10)
        bill={'id':'a','start':NOW,'end':NOW+86400,'consumption':10,'unit':'kWh','source':'manual invoice'}
        import_bills(self.store,[bill]); import_bills(self.store,[bill])
        self.store.counter('8380',NOW,0); self.store.counter('8380',NOW+2*86400,40)
        annual=actual_annual(self.store,NOW,NOW+2*86400)
        self.assertEqual(annual['known_kwh'],30)
        with self.assertRaises(ValueError): import_bills(self.store,[dict(bill,id='b')])
    def test_volume_dated_conversion(self):
        self.store.counter('8380',NOW,0); self.store.counter('8380',NOW+7200,20)
        self.assertIsNone(volume_between(self.store,{},NOW,NOW+7200))
        cfg={'conversions':[{'start':NOW,'end':NOW+3600,'heating_value_mj_m3':36,'correction':1},
                            {'start':NOW+3600,'end':NOW+7200,'heating_value_mj_m3':40,'correction':1}]}
        self.assertAlmostEqual(volume_between(self.store,cfg,NOW,NOW+7200),1.9)
    def test_annual_no_missing_history_as_zero(self):
        cfg={'year_start':'2026-07-01','year_end':'2027-07-01','allowance':15000,'allowance_unit':'kWh'}
        report=AnnualPlanner(self.store,cfg).forecast(NOW,[])
        self.assertIsNone(report['remaining_kwh']); self.assertEqual(report['coverage'],0)
    def test_annual_weather_and_climatology_projection(self):
        start=local_day_bounds('2026-07-01')[0]
        import_bills(self.store,[{'id':'a','start':start,'end':NOW,'consumption':1000,'unit':'kWh','source':'verified invoice'}])
        cfg={'year_start':'2026-07-01','year_end':'2027-07-01','allowance':15000,'monthly_outdoor_normals_c':[5]*12,
             'tariffs':[{'up_to_kwh':15000,'price_per_kwh':10,'currency':'HUF','verified_source':'invoice'},
                        {'up_to_kwh':None,'price_per_kwh':20,'currency':'HUF','verified_source':'invoice'}]}
        report=AnnualPlanner(self.store,cfg).forecast(NOW,[],{'kwh_per_degree_day':2},3)
        self.assertEqual(report['remaining_kwh'],14000)
        self.assertGreater(report['projected_kwh'],1000)
        self.assertIsNotNone(report['cost'])
        self.assertEqual(tariff_cost(15001,cfg),150020)
    def test_weather_quality_and_coverage(self):
        data={'generated_at':NOW,'temperature_unit':'°C','wind_speed_unit':'km/h',
           'hourly':[{'datetime':NOW+i*3600,'temperature':5,'wind_speed':36} for i in range(26)]}
        f=Forecast(data,NOW); self.assertEqual(len(f.horizon(NOW,48)),26)
        self.assertEqual(f.points[0].wind_ms,10)
        with self.assertRaises(ValueError): Forecast(data,NOW+8000)
        with self.assertRaises(ValueError): Forecast(dict(data,temperature_unit='°F'),NOW)
        with self.assertRaises(ValueError): Forecast(dict(data,current_temperature=100),NOW)
        with self.assertRaises(ValueError): Forecast(dict(data,hourly=[dict(data['hourly'][0],wind_speed=-10)]),NOW)
        next_hour=dict(data,current_temperature=8,hourly=[dict(r,datetime=r['datetime']+3000) for r in data['hourly']])
        self.assertEqual(Forecast(next_hour,NOW).horizon(NOW,48)[0].temperature,8)
    def test_warm_optimization_never_burns_allowance(self):
        cfg=validate({'efficiency':.9}); cfg['risk_margin']=0
        result=solve(20,weather(temp=25),{'h_kw_k':.2,'c_kwh_k':10},cfg)
        self.assertEqual(result['status'],'optimal',result.get('reason'))
        self.assertAlmostEqual(result['fuel_kwh'],0,places=5)
    def test_cold_heating_soft_ceiling_not_safety_cutoff(self):
        cfg=validate({'efficiency':.9}); cfg.update(kwh_per_m3=10,preferred_daily_m3=0,soft_ceiling_m3=0)
        result=solve(18,weather(temp=-20),{'h_kw_k':.2,'c_kwh_k':10},cfg)
        self.assertEqual(result['status'],'optimal',result.get('reason'))
        self.assertGreater(result['fuel_kwh'],100)
        self.assertGreaterEqual(min(r['room_c'] for r in result['plan']),15-1e-5)
    def test_solver_infeasible_timeout_and_incomplete(self):
        cfg=validate({'efficiency':.9})
        self.assertEqual(solve(18,weather(temp=-50),{'h_kw_k':5,'c_kwh_k':1},cfg)['status'],'fallback')
        self.assertEqual(solve(18,weather(hours=3),{'h_kw_k':.2,'c_kwh_k':10},cfg)['status'],'fallback')
        with patch('predictive.mpc.linprog',side_effect=RuntimeError('solver failed')):
            self.assertEqual(solve(18,weather(),{'h_kw_k':.2,'c_kwh_k':10},cfg)['status'],'fallback')
    def ready(self):
        for k,v in [('mode','Thermostat'),('pump_control','Auto'),('delta','ON'),('6700',0),('8314',35),('8740',18)]: self.t.ingest(k,v,NOW)
        return {'status':'optimal','plan':[{'at':NOW,'gas_input_kw':5,'tank_transfer_kw':0}]}, {'allowed':True,'gas_allowed':True,'expires':NOW+75,'target':55}
    def test_supervisor_manual_stop_delta_fault_and_stale(self):
        proposal,base=self.ready(); s=SafetySupervisor(self.cfg)
        self.assertTrue(s.validate(proposal,self.t,NOW,base,True)['authoritative'])
        for key,value in [('mode','Manual'),('pump_control','Off'),('delta','OFF'),('6700',1)]:
            old=self.t.readings[key]; self.t.readings[key]=Reading(value,NOW,'state','test')
            self.assertFalse(s.validate(proposal,self.t,NOW,base,True)['authoritative']); self.t.readings[key]=old
        self.assertFalse(s.validate(proposal,self.t,NOW+200,base,True)['authoritative'])
        self.assertFalse(s.validate(proposal,self.t,NOW,base,False)['authoritative'])
    def test_supervisor_preserves_native_dhw_and_cutoff(self):
        proposal,base=self.ready(); s=SafetySupervisor(self.cfg)
        self.t.ingest('8005',168,NOW)
        self.assertFalse(s.validate(proposal,self.t,NOW,base,True)['allow_gas'])
        self.t.readings['8314']=Reading(56,NOW,'°C','measured')
        self.assertFalse(s.validate(proposal,self.t,NOW,base,True)['allow_gas'])
    def test_invalid_solver_actions_are_rejected(self):
        proposal,base=self.ready(); s=SafetySupervisor(self.cfg)
        for row in [{},{'at':NOW,'gas_input_kw':float('nan')},{'at':NOW,'gas_input_kw':True},{'at':NOW,'gas_input_kw':1000}]:
            self.assertFalse(s.validate(dict(proposal,plan=[row]),self.t,NOW,base,True)['authoritative'])
    def test_full_production_engine_with_commissioned_inputs(self):
        proposal,base=self.ready()
        cfg={'automatic_control_commissioned':True,'efficiency':.9,'approved_model':{'h_kw_k':.2,'c_kwh_k':10,'calibration_source':'test heat-meter calibration'}}
        e=Engine(self.store,self.t,cfg)
        e.context(dict(base,events=[{'start':NOW,'end':NOW+2*86400}]),NOW)
        e.ingest_forecast({'generated_at':NOW,'temperature_unit':'°C','current_temperature':5,
            'hourly':[{'datetime':NOW+i*3600,'temperature':5} for i in range(48)]},NOW)
        result=e.tick(NOW)
        self.assertEqual(result['status'],'MPC active',result['reason'])
        self.assertTrue(result['recommendation']['authoritative'])
        self.t.readings['pump_control']=Reading('Off',NOW,'state','operator')
        self.assertFalse(e.tick(NOW+1)['recommendation']['authoritative'])
    def test_no_rising_tank_only_pump(self):
        proposal,base=self.ready(); proposal['plan'][0]['gas_input_kw']=0
        self.t.ingest('8830',60,NOW)
        result=SafetySupervisor(self.cfg).validate(proposal,self.t,NOW,base,True)
        self.assertFalse(result['allow_pump'])
        self.assertFalse(result['allow_gas'])
    def test_capability_boundary_and_simulation(self):
        sent=[]; p=ProductionPublisher(lambda *a:sent.append(a)); s=SimulationPublisher()
        for topic in ['BSB-LAN/0/9/700/set','iopi/bmsiopi/relay_2/set','bms/heating_optimizer/sneaky/set']:
            with self.assertRaises(PermissionError): p.publish(topic,'ON')
            with self.assertRaises(PermissionError): s.publish(topic,'ON')
        p.publish('bms/heating_optimizer/state','{}'); s.publish('simulation/state','{}')
        self.assertEqual(len(sent),1)
    def test_production_fallback_and_plan_slot_restart(self):
        engine=Engine(self.store,self.t,{})
        report=engine.tick(NOW)
        self.assertEqual(report['mode'],'production'); self.assertFalse(report['recommendation']['authoritative'])
        engine.tick(NOW+1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM plans').fetchone()[0],1)
        restarted=Engine(self.store,self.t,{})
        restarted.tick(NOW+2)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM plans').fetchone()[0],1)
    def test_configuration_rejects_uncommissioned_guesses(self):
        for row in [{'comfort_c':99},{'efficiency':2},{'approved_model':{'h_kw_k':.2,'c_kwh_k':10}},
                    {'external_sensors':{'flow_m3h':{'topic':'iopi/foo','verified':False}}}]:
            with self.assertRaises(ValueError): validate(row)
    def test_cycling_and_unknown(self):
        self.assertEqual(cycling(1,20)['average_cycle_minutes'],3)
        self.assertTrue(cycling(1,20)['short_cycling'])
        self.assertIsNone(cycling(None,1)['short_cycling'])
    def test_backtest_isolated_readonly_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.db'; output=Path(directory)/'report.json'
            store=Store(str(source)); store.record('8314',Reading(40,NOW,'°C','measured')); store.close()
            before=source.read_bytes(); result=backtest(source,validate({}),output)
            self.assertEqual(result['physical_commands'],0); self.assertEqual(source.read_bytes(),before)
            self.assertTrue(output.exists())

if __name__=='__main__': unittest.main()
