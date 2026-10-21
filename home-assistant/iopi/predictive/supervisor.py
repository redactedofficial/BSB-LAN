"""Independent final recommendation gate; no boiler/relay write client exists here."""
import math


class SafetySupervisor:
    def __init__(self, config): self.config=config

    def validate(self, proposal, telemetry, now, base, model_ready):
        result={'schema':1,'issued_at':now,'expires':now+75,'authoritative':False,
                'mode':self.config['mode'],'allow_gas':True,'allow_pump':True,
                'return_target':base.get('target',55),'reason':'Conservative existing control'}
        reason=None
        if self.config['mode']!='production': reason='Shadow / disabled mode; existing controller retained'
        elif not self.config.get('automatic_control_commissioned'): reason='Automatic control not commissioned'
        elif not model_ready: reason='Measured room temperature / thermal calibration required'
        elif proposal.get('status')!='optimal': reason=proposal.get('reason','Solver unavailable')
        elif not base or now>=base.get('expires',0): reason='Base permission missing or stale'
        elif telemetry.value('mode',now,30)!='Thermostat': reason='Manual / stopped mode retained'
        elif telemetry.value('pump_control',now,30)=='Off': reason='Manual pump OFF retained'
        elif telemetry.value('delta',now,30)!='ON': reason='No verified Delta demand'
        elif telemetry.value('6700',now,90)!=0: reason='Boiler feedback missing or faulted'
        elif telemetry.value('8314',now,90) is None: reason='Fresh boiler return required'
        elif telemetry.value('8740',now,180) is None: reason='Fresh measured room temperature required'
        elif not proposal.get('plan'): reason='Empty plan'
        if reason:
            result['reason']=reason
            return result
        first=proposal['plan'][0]
        try:
            valid=(type(first['at']) in (int,float) and type(first['gas_input_kw']) in (int,float) and
              now-900<=first['at']<=now+5 and math.isfinite(first['gas_input_kw']) and
              0<=first['gas_input_kw']<=self.config.get('max_fuel_kw',35))
        except (KeyError,TypeError,ValueError): valid=False
        if not valid:
            result['reason']='Rejected invalid / stale first MPC action'
            return result
        result['authoritative']=True
        result['allow_gas']=bool(base.get('gas_allowed',base.get('allowed',False)) and first['gas_input_kw']>=0.2)
        # Never invent tank heat or force a pump from a rising B3 trend.
        result['allow_pump']=bool(base.get('allowed',False) and (first['gas_input_kw']>=0.2 or
            (self.config.get('hydraulics_verified') and self.config.get('tank_average_verified') and first.get('tank_transfer_kw',0)>0.2)))
        supply=telemetry.value('supply_actual',now,90); returning=telemetry.value('return_actual',now,90)
        if first['gas_input_kw']<.2 and self.config.get('flow_verified') and supply is not None and returning is not None and supply<=returning+1:
            result['allow_pump']=False
        target=base.get('target',55)
        curve=self.config.get('approved_water_curve')
        if curve and first['gas_input_kw']>=0.2:
            outside=proposal.get('outside_c')
            if outside is not None:
                target=curve['return_at_0c']-curve['slope']*outside
        result['return_target']=max(30,min(55,target))
        if telemetry.value('8314',now,90)>=result['return_target']:
            result['allow_gas']=False
        if telemetry.value('8005',now,90) in (168,169):
            result['allow_gas']=False
            result['reason']='Native DHW priority; room request deferred'
        else:
            result['reason']='MPC: '+('room charging allowed' if result['allow_gas'] else 'defer room gas; predicted comfort maintained')
        return result


class ProductionPublisher:
    """An allowlist capability boundary, independent of numerical solver code."""
    def __init__(self, send): self.send=send

    def publish(self, topic, payload, retain=False):
        allowed=(topic.startswith('bms/heating_optimizer/') or
                 topic.startswith('homeassistant/sensor/bsb_optimizer/'))
        if not allowed or topic.endswith('/set') or topic.startswith('BSB-LAN/'):
            raise PermissionError('Optimizer cannot publish physical commands')
        return self.send(topic,payload,retain)


class SimulationPublisher:
    def __init__(self): self.messages=[]
    def publish(self, topic, payload, retain=False):
        if not topic.startswith('simulation/'):
            raise PermissionError('Simulation is isolated from all live MQTT topics')
        self.messages.append((topic,payload))
