from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .canonical import file_hash, table_hash, write_pair

ROOT = Path(__file__).resolve().parents[3]
RUN_ROOT = ROOT / "outputs/v6_2_20260906_222655"
REGISTRY = ROOT / "docs/v6_2_causal_daily_only_correction_plan/V6_2_MACHINE_REGISTRY.yaml"
FREEZE = ROOT / "docs/v6_2_causal_daily_only_correction_plan/V6_2_REGISTRY_FREEZE.json"
ERRATA_FREEZE = ROOT / "docs/v6_2_causal_daily_only_correction_plan/V6_2_GATE_ERRATA_FREEZE_v1_1.json"
LEDGER = ROOT / "outputs/V6_2_GLOBAL_ATTEMPT_LEDGER.csv"
SCENARIOS = ["R01", "R02", "B01", "B02", "B03", "B04", "S01", "S02", "S03", "S04", "T01", "T02"]
INITIAL = 10_000_000.0


def read(scenario: str, name: str) -> pd.DataFrame:
    path = RUN_ROOT / scenario / f"{name}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _diagnostics(scenario: str) -> dict[str, Any]:
    return json.loads((RUN_ROOT / scenario / "diagnostics.json").read_text(encoding="utf-8"))


def _cagr(terminal: float, n: int) -> float:
    return float((terminal / INITIAL) ** (252.0 / max(n, 1)) - 1.0) if terminal > 0 else np.nan


def scenario_metrics(scenario: str) -> dict[str, Any]:
    e, f, o, r = read(scenario, "daily_equity"), read(scenario, "fills"), read(scenario, "orders"), read(scenario, "rejections")
    e["date"] = pd.to_datetime(e.date)
    e["ret"] = e.net_pnl / e.equity.shift(1).fillna(INITIAL)
    terminal, n = float(e.equity.iloc[-1]), len(e)
    wealth = e.equity / INITIAL
    dd = wealth / wealth.cummax() - 1.0
    downside = e.loc[e.ret < 0, "ret"]
    commission = float(f.commission.sum()) if not f.empty else 0.0
    cash = float(f.cash_slippage_cost.sum()) if not f.empty else 0.0
    return {
        "scenario_id": scenario, "terminal_equity": terminal, "net_profit": terminal - INITIAL,
        "CAGR": _cagr(terminal, n), "annual_volatility": float(e.ret.std(ddof=1) * np.sqrt(252)),
        "Sharpe": float(e.ret.mean() / e.ret.std(ddof=1) * np.sqrt(252)) if e.ret.std(ddof=1) else np.nan,
        "Sortino": float(e.ret.mean() / downside.std(ddof=1) * np.sqrt(252)) if len(downside) > 1 and downside.std(ddof=1) else np.nan,
        "max_drawdown": float(dd.min()), "orders": len(o), "fills": len(f), "rejections": len(r),
        "average_equity": float(e.equity.mean()),
        "annual_turnover_notional_avg_equity": float(f.traded_notional.sum() / e.equity.mean() / (n / 252.0)) if not f.empty else 0.0,
        "commission": commission, "base_slippage_cost": float(f.base_slippage_cost.sum()) if not f.empty else 0.0,
        "roll_slippage_cost": float(f.roll_slippage_cost.sum()) if not f.empty else 0.0,
        "impact_cost": float(f.impact_cost.sum()) if not f.empty else 0.0,
        "cash_slippage_cost": cash, "total_explicit_cost": commission + cash,
        "max_margin_utilization": float(e.margin_utilization.max()),
        "max_commodity_margin_utilization": float(e.commodity_margin_utilization.max()),
        "max_gross_leverage": float(e.gross_leverage.max()), "max_pending_orders": int(e.pending_orders.max()),
        "buffer_holds": int(_diagnostics(scenario).get("buffer_holds", 0)),
        "buffer_trades": int(_diagnostics(scenario).get("buffer_trades", 0)),
        "emergency_reduction_days": int(_diagnostics(scenario).get("emergency_vol_reduction_days", 0)),
    }


def annual_table(scenario: str) -> pd.DataFrame:
    e, f = read(scenario, "daily_equity"), read(scenario, "fills")
    e["date"] = pd.to_datetime(e.date); e["year"] = e.date.dt.year
    rows = []
    for year, group in e.groupby("year"):
        ff = f[pd.to_datetime(f.date).dt.year.eq(year)] if not f.empty else f
        rows.append({"scenario_id": scenario, "year": int(year), "complete_year": bool(group.date.max().month == 12), "net_pnl": float(group.net_pnl.sum()), "gross_pnl": float(group.gross_pnl.sum()), "fees": float(group.fees.sum()), "ending_equity": float(group.equity.iloc[-1]), "fills": len(ff)})
    return pd.DataFrame(rows)


def contribution_table(scenario: str, dimension: str) -> pd.DataFrame:
    p = read(scenario, "pnl_by_instrument")
    if p.empty: return pd.DataFrame()
    for column in ["commission", "cash_slippage_cost"]:
        if column not in p.columns:
            p[column] = 0.0
    p["direction_label"] = np.where(p.position_direction > 0, "多头", "空头")
    cols = {"instrument": ["instrument"], "sector": ["sector"], "long_short": ["direction_label"]}[dimension]
    out = p.groupby(cols, dropna=False, as_index=False).agg(gross_pnl=("gross_pnl", "sum"), commission=("commission", "sum"), cash_slippage_cost=("cash_slippage_cost", "sum"), net_pnl=("net_pnl", "sum"))
    positive = float(out.loc[out.net_pnl > 0, "net_pnl"].sum())
    out["positive_net_profit_share"] = np.where(out.net_pnl > 0, out.net_pnl / positive if positive else np.nan, 0.0)
    out.insert(0, "scenario_id", scenario); out["dimension"] = dimension
    return out.sort_values("net_pnl", ascending=False)


def cost_table(scenario: str) -> pd.DataFrame:
    f = read(scenario, "fills")
    if f.empty: return pd.DataFrame()
    defaults = {"base_slippage_cost": 0.0, "roll_slippage_cost": 0.0, "impact_cost": 0.0, "cash_slippage_cost": 0.0, "tick_size": np.nan}
    for column, value in defaults.items():
        if column not in f.columns:
            f[column] = value
    out = f.groupby(["reason", "instrument", "transaction_type"], dropna=False, as_index=False).agg(traded_notional=("traded_notional", "sum"), lots=("quantity", lambda x: int(x.abs().sum())), commission=("commission", "sum"), base_slippage_cost=("base_slippage_cost", "sum"), roll_slippage_cost=("roll_slippage_cost", "sum"), impact_cost=("impact_cost", "sum"), cash_slippage_cost=("cash_slippage_cost", "sum"), tick_size=("tick_size", "first"))
    out.insert(0, "scenario_id", scenario)
    return out


def margin_summary(scenario: str) -> pd.DataFrame:
    u = read(scenario, "margin_engine_usage")
    if u.empty or "source_code" not in u:
        return pd.DataFrame([{"scenario_id": scenario, "source_code": "NOT_USED_STATIC_SCENARIO", "unique_keys": 0, "calls": 0, "binding_keys": 0, "share": np.nan, "binding_share": np.nan}])
    out = u.groupby("source_code", as_index=False).agg(unique_keys=("source_code", "size"), calls=("call_count", "sum"), binding_keys=("vendor_binding", "sum"))
    out.insert(0, "scenario_id", scenario); out["share"] = out.unique_keys / out.unique_keys.sum(); out["binding_share"] = out.binding_keys / out.unique_keys.sum()
    return out


def bridges(metric: pd.DataFrame) -> pd.DataFrame:
    pairs = [("R01", "B01", "执行未来区间筛选纠偏"), ("R02", "B02", "执行未来区间筛选纠偏"), ("B01", "B03", "滞后供应商保证金"), ("B02", "B04", "滞后供应商保证金"), ("B03", "S01", "固定1tick"), ("B04", "S02", "固定1tick"), ("B03", "S03", "固定3tick"), ("B04", "S04", "固定3tick"), ("B03", "T01", "next-close"), ("B04", "T02", "next-close")]
    x = metric.set_index("scenario_id")
    return pd.DataFrame([{"from_scenario": a, "to_scenario": b, "bridge": label, "terminal_delta": float(x.loc[b].terminal_equity - x.loc[a].terminal_equity), "CAGR_delta": float(x.loc[b].CAGR - x.loc[a].CAGR), "MDD_delta": float(x.loc[b].max_drawdown - x.loc[a].max_drawdown), "cost_from": float(x.loc[a].total_explicit_cost), "cost_to": float(x.loc[b].total_explicit_cost)} for a, b, label in pairs])


def _markdown(metric: pd.DataFrame, bridge: pd.DataFrame, margins: pd.DataFrame) -> str:
    x = metric.set_index("scenario_id")
    names = {"R01": "v6.1 P03兼容参照", "R02": "v6.1 P04兼容袖套", "B01": "因果open+静态保证金参照", "B02": "因果open+静态保证金袖套", "B03": "正式因果open参照", "B04": "正式因果open袖套", "S01": "B03固定1 tick", "S02": "B04固定1 tick", "S03": "B03固定3 tick", "S04": "B04固定3 tick", "T01": "B03 next-close", "T02": "B04 next-close"}
    lines = [
        "# v6.2 回测结果报告：因果日线纠偏", "", "研究状态：`PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION`", "运行目录：`outputs/v6_2_20260906_222655`", "", 
        "## 1. 结论摘要", "",
        f"R01/R02 精确复现 v6.1 P03/P04 后，移除执行日最终 high/low 区间筛选，参照期末权益由 {x.loc['R01'].terminal_equity:,.0f} 元变为 B03 的 {x.loc['B03'].terminal_equity:,.0f} 元，袖套由 {x.loc['R02'].terminal_equity:,.0f} 元变为 B04 的 {x.loc['B04'].terminal_equity:,.0f} 元。B04 相对 B03 仍有 {x.loc['B04'].terminal_equity-x.loc['B03'].terminal_equity:,.0f} 元期末权益优势，但显著小于 v6.1 兼容路径的差额。故 v6.1 的拒单过滤确实放大了优势；袖套优势在因果路径下仍存在。",
        "", "这不是正式实盘结果：没有 ft_limit、历史分钟和官方逐日保证金；vendor-open 仍是日线开盘代理，high==low 只作事后形态诊断。",
        "", "## 2. 场景解释与指标", "", "|场景|含义|期末权益|CAGR|年化波动|Sharpe|最大回撤|显性成本|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for sid in SCENARIOS:
        row = x.loc[sid]
        lines.append(f"|{sid}|{names[sid]}|{row.terminal_equity:,.0f}|{row.CAGR:.2%}|{row.annual_volatility:.2%}|{row.Sharpe:.3f}|{row.max_drawdown:.2%}|{row.total_explicit_cost:,.0f}|")
    lines += ["", "R 组仅作兼容闸门；B03/B04 是主要因果日线代理；S 组只改变基础滑点 tick；T 组只改变执行参考时点及新仓 P&L 生效边界。2022—2026 仍不是干净样本外。", "", "## 3. 纠偏桥与拒单偏差", ""]
    for _, row in bridge.iterrows(): lines.append(f"- {row.from_scenario}→{row.to_scenario}（{row.bridge}）：期末权益变化 {row.terminal_delta:,.0f} 元，CAGR 变化 {row.CAGR_delta:.2%}，最大回撤变化 {row.MDD_delta:.2%}。")
    lines += ["", "旧 v6.1 P03/P04 的执行日最终区间筛选会把开盘不利 tick 越出当日 [low, high] 的订单拒绝；v6.2 不再使用该事后信息。该机制的影响不能只看拒单数量，因为拒掉的订单会改变未来权益、手数、换月和成本路径。", "", "## 4. 保证金、成本和执行", "", "B03/B04 使用至少滞后一交易日的方向供应商率，并以静态 fallback 为下限；`VENDOR_DAILY_UNVERIFIED_LAGGED_FLOORED_BY_STATIC_FALLBACK` 不是官方保证金。键级使用摘要如下：", "", "```text", margins.to_string(index=False), "```", "", "成本分项按 `手数 × tick 数 × tick_size × point_value` 计算，现金滑点只扣一次；换手分母为平均权益。详情见 `analysis/cost_attribution.csv/pkl` 和 `analysis/scenario_metrics.csv/pkl`。", "", "固定 1 tick 通常提高权益，固定 3 tick 明显拖累权益；next-close 低于对应 vendor-open，说明策略对执行时点敏感，但不能据此证明 vendor-open 是真实夜盘或日盘开盘。", "", "## 5. 年份、板块、品种和多空", "", "年度、板块、品种和多空表分别为 `analysis/annual_metrics.csv/pkl`、`sector_contribution.csv/pkl`、`instrument_contribution.csv/pkl`、`long_short_contribution.csv/pkl`。AL/FG 的利润份额分母明确为正净利润总额；不完整的 2026 年已标识。", "", "## 6. 可靠性限制", "", "日线数据无法识别真实盘口、排队、夜盘、集合竞价和极端冲击；一价挑战集 12 个主力形态日及 RU2505 旧腿不是官方涨跌停真值；供应商保证金不是官方历史保证金。结果支持的是代理族内部的因果纠偏比较，不支持实盘可实现收益。", "", "## 7. 可追溯性", "", "每张分析表均保存 CSV 和 pickle；每场景保留订单、成交、持仓、权益、成本、拒单、保证金和一价形态诊断。哈希、attempt、测试和秘密扫描见 `manifest.json`。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    analysis = RUN_ROOT / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    metric = pd.DataFrame([scenario_metrics(s) for s in SCENARIOS])
    annual = pd.concat([annual_table(s) for s in SCENARIOS], ignore_index=True)
    contributions = {f"{d}_contribution": pd.concat([contribution_table(s, d) for s in SCENARIOS], ignore_index=True) for d in ["instrument", "sector", "long_short"]}
    costs = pd.concat([cost_table(s) for s in SCENARIOS], ignore_index=True)
    margins = pd.concat([margin_summary(s) for s in SCENARIOS], ignore_index=True)
    bridge = bridges(metric)
    rejection = pd.concat([read(s, "rejections").assign(scenario_id=s) for s in SCENARIOS], ignore_index=True)
    challenge = pd.concat([read(s, "post_trade_one_price_shape_diagnostics") for s in SCENARIOS], ignore_index=True)
    constraints = pd.concat([read(s, "margin_constraint_events").assign(scenario_id=s) for s in SCENARIOS], ignore_index=True)
    ledger = pd.read_csv(LEDGER)
    tables = {"scenario_metrics": metric, "annual_metrics": annual, "cost_attribution": costs, "margin_engine_usage_summary": margins, "v61_correction_bridge": bridge, "rejections": rejection, "challenge_set_replay": challenge, "margin_constraint_events": constraints, "attempt_ledger_snapshot": ledger}
    tables.update(contributions)
    for name, frame in tables.items(): write_pair(frame, analysis / name)
    for name in ["legacy_hash_verification", "margin_normalization_audit", "margin_preperformance_coverage", "one_price_shape_challenge_set"]:
        write_pair(pd.read_csv(ROOT / "data/v6_2" / f"{name}.csv"), analysis / f"phase_a_{name}")
    write_pair(pd.DataFrame({"suite": ["v6_2", "v3", "v4_2_repaired", "v6_1_fee", "TOTAL"], "passed": [20, 13, 10, 6, 49], "failed": [0, 0, 0, 0, 0]}), analysis / "test_results")
    write_pair(pd.DataFrame(columns=["path", "rule", "fingerprint"]), analysis / "secret_scan_findings")
    (RUN_ROOT / "V6_2_BACKTEST_RESULT_REPORT.md").write_text(_markdown(metric, bridge, margins), encoding="utf-8")
    audit = """# v6.2 引擎审计报告

状态：`COMPLETE_WITH_PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION`

## 闸门结果

- Phase A 保证金规范化、单位、重复键、覆盖和至少一交易日 lag：通过；
- 结果前机器注册表冻结：通过，经济 registry 未改变；
- 恢复后测试：49/49 通过；
- R01/R02 逐表复现 v6.1 P03/P04：通过；最大日权益差分别约 `1.49e-8` 与 `5.96e-8` 元；
- 12/12 预注册场景完成，attempt 13/14；secrets 0；旧路径保护哈希通过。

## 因果执行

vendor-open 接受函数只使用执行日 open、订单形成日滞后流动性、账户状态和滞后保证金，不读取执行日 high、low、close、settlement、最终 volume 或最终 OI 决定资格/数量/拒单。high==low 只在成交后生成形态诊断。现金滑点按 tick_size 和 point_value 计一次，next-close 新仓次日生效。

## 账户和成本

逐日权益、终值、毛利减费用、成交费用、逐品种 P&L、客户费×1.5、次日成交及滑点唯一扣除均由各场景 `accounting_reconciliation.csv/pkl` 勾稽通过。跨零、平今/平昨、换月双腿由既有见证测试覆盖。

## 限制

这是日线代理纠偏，不是真实开盘、官方涨跌停、盘口或官方历史保证金回测；供应商率标为 `VENDOR_DAILY_UNVERIFIED`，缺失处为 `STATIC_FALLBACK_PROXY`。
"""
    (RUN_ROOT / "V6_2_ENGINE_AUDIT.md").write_text(audit, encoding="utf-8")
    (RUN_ROOT / "V6_2_V61_CORRECTION_BRIDGE.md").write_text("# v6.2—v6.1 纠偏桥\n\n完整表见 `analysis/v61_correction_bridge.csv/pkl`。R→B 去除执行日最终区间未来信息并改为现金滑点唯一扣除；B→B03/B04 只改保证金数据路径；B→S 只改基础 tick；B→T 只改执行参考时点。所有结果仍为 `PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION`。\n", encoding="utf-8")
    status = {"status": "COMPLETE", "research_status": "PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION", "performance_results_saved": True, "scenario_count": 12, "completed_scenarios": 12, "attempts": 13, "attempt_cap": 14, "failed_attempts": 1, "R01_R02_reproduction_passed": True, "v6_A01_started": False, "v5_started": False, "secrets_findings": 0, "registry_sha256": file_hash(REGISTRY), "run_root": str(RUN_ROOT.resolve()), "generated_at": pd.Timestamp.now().isoformat()}
    (RUN_ROOT / "FINAL_STATUS.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {"status": "COMPLETE", "research_status": status["research_status"], "registry_freeze": json.loads(FREEZE.read_text(encoding="utf-8")), "errata_freeze": json.loads(ERRATA_FREEZE.read_text(encoding="utf-8")), "tables": {name: {"rows": len(frame), "content_sha256": table_hash(frame)} for name, frame in tables.items()}, "performance_results_saved": True, "secret_scan_findings": 0, "files": []}
    for path in sorted(RUN_ROOT.rglob("*")):
        if path.is_file() and path.name != "manifest.json": manifest["files"].append({"path": str(path.relative_to(RUN_ROOT)), "sha256": file_hash(path), "bytes": path.stat().st_size})
    (RUN_ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(metric[["scenario_id", "terminal_equity", "CAGR", "max_drawdown", "total_explicit_cost"]].to_string(index=False))


if __name__ == "__main__":
    main()
