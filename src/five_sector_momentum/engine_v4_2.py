"""Fixed-calendar single strategies and strictly netted two-horizon sleeve."""
import math
import numpy as np
import pandas as pd
from .engine_v3 import BacktestEngineV3
from .engine_v4_1 import BacktestEngineV41, SleeveEngineV41, COST_SPECS, combined_sleeve_signal


class BacktestEngineV42(BacktestEngineV41):
    def __init__(self, settings, data, signals, fee_schedule, calendar):
        if settings.raw.get('version') != 'v4_2':
            raise ValueError('Independent v4_2 settings required')
        BacktestEngineV3.__init__(self, settings, data, signals, fee_schedule)
        self._cost = COST_SPECS['C3']
        self.weekly_signal_dates = set(calendar.weekly_signal_dates(sorted(data.mapping.date.unique())))

    def run_v4_2(self, scenario):
        return self.run_v4_1(scenario)


class SleeveEngineV42(BacktestEngineV42):
    def __init__(self, settings, data, signals_by_horizon, fee_schedule, calendar):
        if set(signals_by_horizon) != {'single_20_skip5', 'single_250'}:
            raise ValueError('Only fixed 20skip5 / 250 sleeve is registered')
        combined = combined_sleeve_signal(signals_by_horizon)
        super().__init__(settings, data, combined, fee_schedule, calendar)
        self.directions_by_horizon = {key: bundle.directions.set_index(['date','instrument']).direction.to_dict() for key,bundle in signals_by_horizon.items()}
        self.internal_target_rows=[]
        self.net_target_rows=[]
        self.risk_rows=[]

    def _calculate_targets(self, date, equity, positions, scenario, portfolio_returns):
        annualizer=math.sqrt(float(self.volatility['annualization_days']))
        rows=[]
        for horizon in sorted(self.directions_by_horizon):
            directions=self.directions_by_horizon[horizon]
            for sector, weight in self.portfolio['sector_risk_weights'].items():
                legs=[(instrument,int(directions.get((date,instrument),0))) for instrument,row in self.instrument_meta.iterrows()
                      if row['sector']==sector and directions.get((date,instrument),0)]
                budget=equity*scenario.annual_vol_target*float(weight)*.5
                if not legs:
                    rows.append({'date':date,'horizon':horizon,'sector':sector,'instrument':None,'contract':None,
                                 'direction':0,'internal_target':0,'allocated_annual_risk':budget,'internal_annual_risk':0.,
                                 'unused_annual_risk':budget,'risk_fraction':float(weight)*.5,'equity':equity})
                    continue
                for instrument,direction in legs:
                    contract=self.mapping.get((date,instrument))
                    vol=self.price_vol.get((date,instrument),np.nan)
                    one_lot=0.
                    if contract and vol is not None and np.isfinite(vol) and vol>0:
                        one_lot=self._contract_value(contract,'point_value',self._fallback(instrument)[0])*vol*annualizer
                    per_leg=budget/len(legs)
                    lots=int(math.floor(per_leg/one_lot)) if one_lot>0 else 0
                    rows.append({'date':date,'horizon':horizon,'sector':sector,'instrument':instrument,'contract':contract,
                                 'direction':direction,'internal_target':direction*lots,'allocated_annual_risk':per_leg,
                                 'internal_annual_risk':lots*one_lot,'unused_annual_risk':per_leg-lots*one_lot,
                                 'risk_fraction':float(weight)*.5/len(legs),'equity':equity})
        self.internal_target_rows.extend(rows)
        net={}; gross={}
        for row in rows:
            c=row['contract']; q=int(row['internal_target'])
            if c:
                net[c]=net.get(c,0)+q; gross[c]=gross.get(c,0)+abs(q)
        targets={c:q for c,q in net.items() if q}
        # All caps/scaling below operate on the one REAL net portfolio only.
        SleeveEngineV41._cap_final_liquidity(self,date,targets)
        after_liquidity=targets.copy()
        exante, diversification=self._scale_to_exante_volatility(date,targets,equity,scenario.annual_vol_target)
        trailing, realized=self._scale_by_realized_volatility(targets,portfolio_returns,scenario.annual_vol_target)
        # Hard margin/leverage constraints are applied once to executable net
        # targets by the inherited scheduler AFTER its one buffer application.
        for c in sorted(net):
            self.net_target_rows.append({'date':date,'contract':c,'instrument':self._instrument_for_contract(c),
                                         'internal_gross_lots':gross[c],'raw_net_target':net[c],
                                         'cancelled_internal_lots':gross[c]-abs(net[c]),
                                         'liquidity_capped_net':after_liquidity.get(c,0),
                                         'scaled_net_optimal':targets.get(c,0),
                                         'internal_order_fees':0.})
        self.risk_rows.append({'date':date,'equity':equity,'nominal_annual_risk':equity*scenario.annual_vol_target,
                               'exante_vol_before_scaling':exante,'diversification_multiplier':diversification,
                               'trailing_realized_volatility':trailing,'realized_vol_multiplier':realized})
        return targets,{'commodity_margin_scaled':False,'total_margin_scaled':False,'commodity_leverage_scaled':False,
                        'exante_vol_before_scaling':exante,'diversification_multiplier':diversification,
                        'trailing_realized_volatility':trailing,'realized_vol_multiplier':realized}

    def _scheduled_targets(self,date,optimal,positions,equity,sizing_diag,scenario):
        # Corrected v4.1's net-direction scheduler, not a vote-count direction.
        saved={}
        for instrument in self.instrument_meta.index:
            key=(date,instrument); saved[key]=self.directions.get(key)
            target=int(optimal.get(self.mapping.get(key),0))
            self.directions[key]=int(np.sign(target))
        try:
            return BacktestEngineV3._scheduled_targets(self,date,optimal,positions,equity,sizing_diag,scenario)
        finally:
            for key,value in saved.items():
                if value is None:
                    self.directions.pop(key,None)
                else:
                    self.directions[key]=value
