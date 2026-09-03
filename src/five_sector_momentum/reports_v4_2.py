"""Chinese reports with every table linked to its underlying data."""
import json
import numpy as np
import pandas as pd
from .analytics_v4_2 import FAST,SLOW,SLEEVE,STRESS,REF

NAMES={FAST:'20日跳5日',SLOW:'250日单体',SLEEVE:'50/50风险袖套',STRESS:'袖套固定3 tick',REF:'v3正式252日参照'}
PHASES={'full':'全样本','insample':'2015—2021样本内','validation':'2022—2026验证期'}
METRICS={'cagr':'年化收益','vol':'年化波动率','sharpe':'Sharpe','sortino':'Sortino','mdd':'最大回撤','calmar':'Calmar','longest_underwater':'最长水下交易日','total_return':'区间收益'}


def reports_v42(settings,root):
    def read(name):return pd.read_pickle(root/(name+'_v4_2.pkl'))
    def table(frame,source):
        f=frame.copy()
        for c in f.columns:
            if pd.api.types.is_float_dtype(f[c]):f[c]=f[c].map(lambda x:'缺失/不足' if pd.isna(x) else f'{x:,.4f}')
        return f.to_markdown(index=False)+f'\n\n底层：[{source}.csv]({source}.csv)及同名pickle。\n'
    def perf_table(frame):
        f=frame[['strategy','phase','cagr','vol','sharpe','sortino','mdd','calmar','longest_underwater']].copy()
        f.strategy=f.strategy.map(lambda x:NAMES.get(x,x));f.phase=f.phase.map(lambda x:PHASES.get(x,x))
        for c in ['cagr','vol','mdd']:f[c]=f[c].map(lambda x:f'{x:.2%}')
        return f.rename(columns={'strategy':'方案','phase':'阶段',**METRICS})
    perf=read('performance');base=perf.loc[perf.basis.eq('net')&perf.exclusion.eq('none')&perf.phase.isin(PHASES)&perf.strategy.isin(NAMES)]
    point=base.set_index(['strategy','phase']);ci=read('bootstrap_confidence_intervals')
    corr=read('conditional_drawdown_correlations');netcorr=corr.loc[corr.basis.eq('net')&corr.phase.isin(PHASES)&corr.method.eq('pearson')]
    overlap=read('drawdown_overlap');protection=read('conditional_protection');netting=read('netting_summary');risk=read('equal_realized_risk');contrib=read('contributions')
    gates=read('reproduction_and_repair_gate');diffs=read('calendar_repair_differences');costs=read('cost_turnover')
    uncertainty=ci.loc[ci.type.eq('paired')&ci.basis.eq('net')&ci.reference.eq(SLOW)&ci.metric.isin(['sharpe','mdd','calmar','longest_underwater'])].copy()
    sleeve_full=point.loc[(SLEEVE,'full')];slow_full=point.loc[(SLOW,'full')];sv=point.loc[(SLEEVE,'validation')];lv=point.loc[(SLOW,'validation')]
    delta_dd=sleeve_full.mdd-slow_full.mdd
    equal_full=risk.set_index(['strategy','phase']);equal_dd=equal_full.loc[(SLEEVE,'full'),'mdd']-equal_full.loc[(SLOW,'full'),'mdd']
    walk=read('walk_forward');stitch=walk.loc[walk.slice.eq('next_year_stitched')].set_index('strategy')
    deleted=perf.loc[perf.basis.eq('net')&perf.exclusion.eq('delete_both')&perf.phase.isin(PHASES)&perf.strategy.isin([SLEEVE,SLOW])]
    text=f'''# 中国期货五板块动量 v4.2 回测与结论报告

研究：20日跳5日—250日固定50/50风险袖套与回撤期相关性。交易样本2015-01-05至2026-08-31，预热自2014；2026为不完整年度。初始资金1,000万元。本报告完成授权的独立日历修复及原定G1/G2/S1/S2，不进入其他备选研究或v5。

## 1. 先说结论与证据边界

袖套全样本年化收益{float(sleeve_full.cagr):.2%}，Sharpe {float(sleeve_full.sharpe):.3f}，最大回撤{float(sleeve_full.mdd):.2%}；250日单体对应为{float(slow_full.cagr):.2%}、{float(slow_full.sharpe):.3f}、{float(slow_full.mdd):.2%}。袖套相对慢周期的最大回撤改善为{float(delta_dd):.2%}（正数表示回撤减轻）；事后统一到慢周期实现波动率后，改善为{float(equal_dd):.2%}。

验证期袖套年化收益{float(sv.cagr):.2%}、Sharpe {float(sv.sharpe):.3f}；250日单体为{float(lv.cagr):.2%}、{float(lv.sharpe):.3f}。是否存在有用的分散，必须结合下文条件保护、同风险比较、删年及不确定性，不应仅看全样本相关。

来源：`performance_v4_2.csv`、`equal_realized_risk_v4_2.csv`。本轮没有优化权重，没有根据结果添加实验。最终建议见第9节；“不替换”不等于证明旧策略可直接实盘。

## 2. 周度日历修复与原基准影响

信号日不再取行情文件中每周最后一行，而由独立交易所日历确定。数据截止周中时继续持有上一周方向；不会把截止日升级为信号日。保留节假日最后交易日，不改成机械每周五。

G1/G2实际权益、持仓、成交及成本保持不变（金额容差0.01元）。严格逐表复现不是全部相同：2026-08-31是周一，旧版本末日伪周度更新被去除，末日目标、待执行订单及相关风险诊断改变。这是查看结果前注册的修复影响例外，所有差异保留。不能说日历修复令历史收益提高了。

'''+table(gates,'reproduction_and_repair_gate_v4_2')+'''
第一轮比较器将daily_equity文件中的待执行订单数与目标风险缩放倍数误归类为实际账户字段，先行拦下；修正分类后只复核已保存G1，没有重跑引擎。首次检查保存在`gate_field_classification_attempt_01`。没有放宽现金容差或隐藏差异。

## 3. 策略、成本和净额机制

五板块各20%风险预算；每板块20日跳5日与250日各固定10%。农业C/M/P/JD/LH/CF/SR/AP、化工FG/MA/UR/RU/SP/SC各自板块按各周期独立选最强正值做多、最弱负值做空；RB/T/AL按各周期Score正负决定方向。完整历史不足或流动性不合格保持无信号，未用周期份额不转移。品种上市前没有合约/完整观察窗口，不会产生头寸。

Score使用Panama收盘绝对点差窗口均值/同窗口样本标准差×√252；快速窗口20日且shift(5)，慢速250日不跳过；手数风险估计仍为35日robust EWMA，不是把仓位波动率也改成20/250日。两个内部目标按真实合约相加后，才进行共同约束与一次10%buffer。只对真实净订单收费，内部抵消费用为零。

保留27.5%年化目标、252日协方差共同缩放、63日实现波动率反馈、120%紧急阈值、混合周度、国债/商品原限制、次日开盘及拒单/参与率/部分成交。相关性不分配周期或板块相对预算，只参与统一组合缩放。S1客户手续费为交易所历史费用×1.5，正常基础tick、换月额外tick及冲击继承v4.1；S2仅基础滑点改为3 tick。

v4.2袖套与冻结旧袖套的实现区别：内部目标不先做流动性截断；净额后执行一次该截断和统一缩放。保证金/杠杆硬检查在buffer后真实可执行净目标上执行一次，不在内部袖套重复执行。单体G1/G2保持旧执行方式以核验原参照。详细阶段目标在各S1/S2目录`internal_targets`、`net_target_stages`、`risk_stages`和`targets`文件，真实订单仅见`orders/fills`。

## 4. 成本后全样本、样本内与验证期

'''+table(perf_table(base),'performance_v4_2')+'''
日收益由当日净盈亏/前日权益计算；年化按252交易日。回撤包含初始权益峰值锚点；Sortino采用全体交易日的下行二阶矩，旧报告只在负收益日平均的口径不同，因此Sortino不能直接与旧表逐数字比较。净收益、CAGR、成本和实际权益并未因此改动。

逐年结果在`performance_v4_2`中phase为年份的行；亏损年应查看total_return<0。滚动评估见下表：五年训练期只做评估，下一年保持固定方案，不在各年训练期择优换策略。

'''+table(walk.loc[walk.strategy.isin(NAMES)&walk.slice.eq('next_year_stitched'),['strategy','slice','cagr','sharpe','mdd','longest_underwater']],'walk_forward_v4_2')+'''
## 5. 回撤错位是否构成保护

以下系数基于成本后收益。每个阶段独立重建初始峰值，与分阶段Bootstrap一致；全样本事件表另外保留跨年度完整回撤。条件日少于20不报告系数。

'''+table(netcorr.loc[netcorr.condition.isin(['unconditional','any_slow','moderate_slow','deep_slow','moderate_both','deep_both','worst_equal_weight_0.05','worst_equal_weight_0.01'])], 'conditional_drawdown_correlations_v4_2')+table(protection.loc[protection.basis.eq('net')&protection.phase.isin(PHASES)&protection.drawdown_strategy.eq(SLOW)],'conditional_protection_v4_2')+'''
条件累计收益是筛选日期后复合的诊断值，不是一笔从回撤起点一直持有到终点的交易；真正连续峰谷保护见`peak_trough_protection_v4_2`。低相关但对方回撤期仍亏损，不足以证明“保险”；应同时看亏损减轻及同风险组合的实际路径。

## 6. 同风险、删年、集中度与成本压力

同风险比较只事后乘固定倍数使阶段波动率与250日相同，不加入资金/保证金/交易反馈，不是额外可交易策略。

    '''+table(perf_table(risk.loc[risk.strategy.isin(NAMES)]),'equal_realized_risk_v4_2')+table(perf_table(deleted),'performance_v4_2')+table(read('concentration').loc[lambda f:f.strategy.isin([FAST,SLOW,SLEEVE])&f.phase.eq('full')],'concentration_v4_2')+table(contrib.loc[contrib.strategy.isin([SLEEVE,SLOW])&contrib.phase.eq('full')&contrib.dimension.isin(['sector','instrument','position_direction'])].sort_values('net_pnl',ascending=False).head(30),'contributions_v4_2')+'''
固定3 tick验证期是否为正请直接对照第4节压力行。所有已注册结果都保留；不删去表现不佳的压力或年份。

## 7. 净额、成本与真实交易量

'''+table(netting,'netting_summary_v4_2')+table(costs.loc[costs.strategy.isin(NAMES)&costs.phase.eq('full')],'cost_turnover_v4_2')+'''
内部目标抵消量是“手数×日期”的持仓量统计，目标变化抵消量才与潜在换手有关；二者都不是实际成交。S1/S2共享权益、风险缩放、buffer及容量约束，不能用两条单体成交简单相加作精确非净额反事实。

`cancelled_target_cost_proxy_v4_2`提供被抵消原始目标变化的基础滑点与按开仓费用计的线性报价；不含buffer、约束、平仓类别、冲击和换月，不可称现金节省或保守上下界。没有新跑一个非净额账户，因而精确已实现现金节省不能被识别。本报告没有让任何虚拟费用进入真实权益。

buffer/紧急减仓详见`buffer_statistics_v4_2`；保证金和杠杆见`margin_leverage_v4_2`，全日数据见每个场景`daily_equity`。内部虚拟风险的实际波动率估算见`internal_virtual_realized_risk_v4_2`，它是在原始内部目标次日开盘、无成本、未过约束情况下的诊断，不是实际分账户收益。最终真实板块风险贡献见`sector_realized_risk_contributions_v4_2`，名义10%份额不等于事后风险贡献恒定10%。

## 8. 联合Bootstrap的不确定性

固定seed20260902、20交易日移动区块、每阶段2000次。所有路径共用同次抽样日期；S2同抽样但不是额外独立投资策略。每次重新计算峰值、最大回撤和回撤条件，不能抽样预先汇总的事件数。

'''+table(uncertainty,'bootstrap_confidence_intervals_v4_2')+'''
以上difference为袖套减参照；mdd为负数，差值>0表示回撤改善；最长水下天数差值<0才是改善。q05/q95为90%区间，q025/q975为95%区间。概率只是对当前历史的重采样支持，不能当作未来成功率。全量抽样与逐次统计见`bootstrap_blocks`、`bootstrap_source_calendar`、`bootstrap_draws`、`bootstrap_paired`、`bootstrap_condition_draws`的CSV/pickle；块起点、长度与源日期表可完整重建每次所有日期，阶段间不混块。

## 9. 方案选择：不把分散证据等同于替换证据

'''
    criterion=[]
    criterion.append({'规则':'样本内与验证期CAGR为正','判断':'通过' if point.loc[(SLEEVE,'insample'),'cagr']>0 and sv.cagr>0 else '不通过'})
    shp=uncertainty.loc[uncertainty.phase.eq('validation')&uncertainty.metric.eq('sharpe')].iloc[0]
    criterion.append({'规则':'验证期及滚动Sharpe不显著差于250日','判断':f'验证期差{sv.sharpe-lv.sharpe:.3f}，滚动差{stitch.loc[SLEEVE,"sharpe"]-stitch.loc[SLOW,"sharpe"]:.3f}；95%区间[{shp.q025:.3f},{shp.q975:.3f}]，不能将未显著差异视为非劣证明'})
    criterion.append({'规则':'回撤或水下时间改善','判断':f'最大回撤改善{delta_dd:.2%}；水下天数变化{int(sleeve_full.longest_underwater-slow_full.longest_underwater)}'})
    criterion.append({'规则':'同实现风险仍改善回撤','判断':f'{equal_dd:.2%}，'+('点估计支持' if equal_dd>0 else '不支持')})
    ds=deleted.loc[deleted.strategy.eq(SLEEVE)]
    criterion.append({'规则':'同时删除2020/2024不结构失效','判断':'各阶段CAGR仍为正，仅构成有限支持' if ds.cagr.gt(0).all() else '至少一个阶段CAGR非正'})
    criterion.append({'规则':'固定3 tick验证期为正','判断':'通过' if point.loc[(STRESS,'validation'),'cagr']>0 else '不通过'})
    criterion.append({'规则':'净额成本不抵消分散','判断':'实际净成本已计入；精确非净额现金节省不可识别，见第7节'})
    criterion.append({'规则':'不依赖FG/单板块/少数年份','判断':'按集中度及删年证据评估；高占比不得被低相关抵消'})
    criterion.append({'规则':'Bootstrap多数支持且披露跨零','判断':'见第8节逐项概率，不能只取有利指标'})
    criterion.append({'规则':'未来函数/账户/复现','判断':'独立修复及末端影响验收；旧版本不回写，完整测试和账本见审计报告'})
    decision=pd.DataFrame(criterion);decision.to_csv(root/'recommendation_rules_v4_2.csv',index=False,encoding='utf-8-sig');decision.to_pickle(root/'recommendation_rules_v4_2.pkl')
    text+=table(decision,'recommendation_rules_v4_2')+'''
本轮不据此自动替换v3正式信号或250日单体。只有原计划十条同时获得充分支持，袖套才可列为长期并行观察候选；“支持部分分散”和“足够替换基准”是不同结论。验证期已被此前研究多次查看，不能表述为干净样本外证明。

## 10. 最重要限制与人工复核顺序

1. 日历为本次查询的供应商历史日历，并非每年公告的完整时点数据库；没有伪造历史公告发布时间。五所共同日期一致和节假日对照不能排除全部历史修订。
2. 费用代理、日线不利tick、换月tick和参与率冲击沿用旧基准，可能重叠；日线看不到盘口、排队、夜盘和极端流动性。代理参数不是实盘账单。
3. 未上市/窗口不足风险份额闲置；早期组合实际有效板块较少。缺失信号不回填。
4. 持仓整数化、共同缩放和权益反馈使50/50名义预算不等于50/50日收益，更不等于简单平均两条独立净值。
5. 旧按日净盈亏记录的多空标签在同日反手时沿用日初方向，属于粗粒度归因；年度/品种/账户勾稽仍成立，不能据此精确拆分日内多空交易损益。
6. 删年和等风险曲线是事后诊断，不保留被删期间的完整交易反馈；Bootstrap不创造新行情，极端风险和结构变化无法由有限样本证明。

优先复核：`calendar_repair_differences_v4_2`及每场景`independent_contract_ledger`；S1/S2的`internal_targets`→`net_target_stages`→`targets`→`orders/fills`；`peak_trough_protection`及`drawdown_events`；验证期/删年/3 tick；`bootstrap_confidence_intervals`与完整抽样表。全部数据表同名CSV/pickle保留。
'''
    (root/'BACKTEST_RESULT_REPORT_v4_2.md').write_text(text,encoding='utf-8')
    corrtext='''# v4.2 回撤期相关性专项报告

本报告按成本后与同路径成本前诊断收益分别分析。成本前诊断收益仍以原前日净权益作分母；另外的冻结原手数人民币成本前权益是初始资本加逐日成本前盈亏，不能把两条曲线混称为零成本重新回测。

## 1. 无条件与回撤条件

'''+table(netcorr,'conditional_drawdown_correlations_v4_2')+'''
## 2. 回撤重合与保护

'''+table(overlap.loc[overlap.basis.eq('net')&overlap.phase.isin(PHASES)],'drawdown_overlap_v4_2')+table(protection.loc[protection.basis.eq('net')&protection.phase.isin(PHASES)],'conditional_protection_v4_2')+'''
## 3. 主要峰谷事件

'''
    events=read('drawdown_events');corrtext+=table(events.loc[events.basis.eq('net')&events.strategy.isin([FAST,SLOW,SLEEVE])&events.severity_rank.le(5)],'drawdown_events_v4_2')
    ep=read('peak_trough_protection');corrtext+=table(ep.loc[ep.basis.eq('net')&ep.drawdown_strategy.eq(SLOW)].nsmallest(10,'source_depth'),'peak_trough_protection_v4_2')
    corrtext+='''
主事件表是事后峰—谷—恢复识别，不是可交易择时。保护要求快周期在慢周期下跌过程中有正贡献或实际减损；不能仅用正日比例或低相关替代。

## 4. 滚动、尾部和状态转换

'''+table(read('rolling_correlation_summary'),'rolling_correlation_summary_v4_2')+table(read('tail_risk').loc[lambda f:f.basis.eq('net')&f.phase.isin(PHASES)],'tail_risk_v4_2')+'''
全部63/126/252日相关路径及低于0转高于0.5的事件分别在`rolling_correlations_v4_2`与`correlation_state_transitions_v4_2`。转换采用低状态后首次高状态，连续高状态只计一次；中间区间不重复触发。最差日/周/月按两周期等权收益最差十期排序，见`joint_worst_periods_v4_2`；不意味着两者每期都为负。

下行beta是慢周期负日时快对慢的OLS斜率，并同时提供反向估计；5%/1%共同落尾和经验尾依赖是有限样本频率，不是渐近尾依赖参数。相关性条件观测不足20时不估计。

## 5. 联合Bootstrap

'''+table(ci.loc[ci.type.eq('conditions')&ci.basis.eq('net')&ci.statistic.isin(['moderate_slow_pearson_minus_unconditional','deep_slow_pearson_minus_unconditional','moderate_both_pearson_minus_unconditional','moderate_fast_slow_jaccard'])],'bootstrap_confidence_intervals_v4_2')+'''
与每阶段原始观察相同，在重采样阶段内重新构建权益峰值和回撤状态。不能把原样本的回撤布尔掩码直接重抽后视作新路径回撤。每项有效重复数和跨零区间必须一起解释。

总体选择、同风险比较及费用限制见[总报告](BACKTEST_RESULT_REPORT_v4_2.md)。结论只能限定于已观察历史，不保证未来危机时仍分散。
'''
    (root/'DRAWDOWN_CORRELATION_REPORT_v4_2.md').write_text(corrtext,encoding='utf-8')
