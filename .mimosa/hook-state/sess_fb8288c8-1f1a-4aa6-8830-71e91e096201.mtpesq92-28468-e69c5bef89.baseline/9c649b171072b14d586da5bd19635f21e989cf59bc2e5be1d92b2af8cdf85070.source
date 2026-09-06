from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _check(name: str, actual: float, expected: float, tolerance: float = 0.01) -> dict[str, object]:
    difference = float(actual - expected)
    return {
        "检查项": name,
        "实际值": float(actual),
        "期望值": float(expected),
        "差异": difference,
        "容差": tolerance,
        "是否通过": abs(difference) <= tolerance,
    }


def _write_both(frame: pd.DataFrame, base: Path) -> None:
    frame.to_csv(base.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    frame.to_pickle(base.with_suffix(".pkl"))


def main() -> int:
    parser = argparse.ArgumentParser(description="复核v3正式基准账户、成本和执行记录")
    parser.add_argument("run_root")
    parser.add_argument("--initial-capital", type=float, default=10_000_000.0)
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    baseline = root / "00_formal__formal_baseline"

    equity = pd.read_pickle(baseline / "daily_equity.pkl").sort_values("date")
    fills = pd.read_pickle(baseline / "fills.pkl")
    pnl = pd.read_pickle(baseline / "pnl_by_instrument.pkl")
    contribution = pd.read_pickle(root / "pnl_contribution_baseline_v3.pkl")
    metrics = pd.read_pickle(root / "scenario_metrics_v3.pkl")
    formal = metrics.loc[metrics["标签"].eq("formal_baseline")].iloc[0]
    diagnostics = json.loads((baseline / "diagnostics.json").read_text(encoding="utf-8"))

    previous = equity["equity"].shift(1).fillna(args.initial_capital)
    all_contribution = contribution[contribution["阶段"].eq("全样本")]
    checks = [
        _check("逐日权益增量=逐日净盈亏（最大绝对差）", float((equity["equity"] - previous - equity["net_pnl"]).abs().max()), 0.0),
        _check("账户累计净盈亏=期末权益-初始资金", float(equity["net_pnl"].sum()), float(equity["equity"].iloc[-1] - args.initial_capital)),
        _check("逐日毛盈亏-手续费=逐日净盈亏", float((equity["gross_pnl"] - equity["fees"]).sum()), float(equity["net_pnl"].sum())),
        _check("成交手续费=账户手续费", float(fills["commission"].sum()), float(equity["fees"].sum())),
        _check("逐品种毛盈亏=账户毛盈亏", float(pnl["gross_pnl"].sum()), float(equity["gross_pnl"].sum())),
        _check("逐品种手续费=账户手续费", float(pnl["commission"].sum()), float(equity["fees"].sum())),
        _check("逐品种净盈亏=账户净盈亏", float(pnl["net_pnl"].sum()), float(equity["net_pnl"].sum())),
        _check("贡献表净利润=账户净盈亏", float(all_contribution["净利润_元"].sum()), float(equity["net_pnl"].sum())),
        _check("贡献表成本前-滑点-手续费=净利润", float((all_contribution["交易成本前盈亏_元"] - all_contribution["滑点成本_元"] - all_contribution["手续费_元"]).sum()), float(all_contribution["净利润_元"].sum())),
        _check("成交滑点成本=场景指标", float(fills["slippage_cost"].sum()), float(formal["滑点成本_元"])),
        _check("成交手数=场景指标", float(fills["quantity"].abs().sum()), float(formal["成交手数"]), tolerance=0.0),
        _check("客户手续费=交易所手续费×1.5", float(fills["commission"].sum()), float(fills["exchange_commission"].sum() * 1.5)),
        _check("代理费用成交分段数=诊断值", float(fills["fee_is_proxy"].astype(bool).sum()), float(diagnostics["fee_proxy_fill_segments"]), tolerance=0.0),
        _check("成交参与率不超过5%（最大超限）", float(max(0.0, fills["participation_rate"].max() - 0.05)), 0.0, tolerance=1e-12),
        _check("费率规则编号缺失数", float(fills["fee_rule_id"].isna().sum()), 0.0, tolerance=0.0),
        _check("费用来源链接缺失数", float(fills["fee_source_url"].isna().sum()), 0.0, tolerance=0.0),
    ]
    checks_frame = pd.DataFrame(checks)

    expected_impact = np.select(
        [fills["participation_rate"].le(0.01), fills["participation_rate"].le(0.03)],
        [0.0, 1.0], default=2.0,
    )
    impact_mismatch = int((fills["impact_ticks"].to_numpy() != expected_impact).sum())
    order_group = ["date", "created_date", "contract", "order_quantity", "attempt", "reason"]
    split_types = fills.groupby(order_group)["transaction_type"].agg(lambda values: set(values))
    cross_zero_orders = int(split_types.map(lambda values: "open" in values and any(item.startswith("close_") for item in values)).sum())
    roll_types = fills[fills["reason"].eq("roll")].groupby(["date", "instrument"])["transaction_type"].agg(lambda values: set(values))
    complete_roll_dates = int(roll_types.map(lambda values: "open" in values and "close_non_today" in values).sum())
    statistics = pd.DataFrame([
        {"统计项": "成交分段数", "数值": len(fills), "说明": "手续费按分段查表"},
        {"统计项": "开仓分段数", "数值": int(fills["transaction_type"].eq("open").sum()), "说明": "open"},
        {"统计项": "非日内平仓分段数", "数值": int(fills["transaction_type"].eq("close_non_today").sum()), "说明": "close_non_today"},
        {"统计项": "平今分段数", "数值": int(fills["transaction_type"].eq("close_today").sum()), "说明": "日频次日开盘模型通常为0；引擎由测试覆盖"},
        {"统计项": "跨零反手订单数", "数值": cross_zero_orders, "说明": "同一订单同时含平仓与反向开仓段"},
        {"统计项": "完整换月日期×品种数", "数值": complete_roll_dates, "说明": "同日旧约平仓+新约开仓，双边计费"},
        {"统计项": "市场冲击分段数", "数值": int(fills["impact_ticks"].gt(0).sum()), "说明": "基于订单形成日滞后成交量"},
        {"统计项": "市场冲击阶梯不匹配数", "数值": impact_mismatch, "说明": "应为0"},
        {"统计项": "代理费用成交分段数", "数值": int(fills["fee_is_proxy"].astype(bool).sum()), "说明": "不可解释为真实历史账单"},
        {"统计项": "代理费用成交分段占比", "数值": float(fills["fee_is_proxy"].astype(bool).mean()), "说明": "按成交分段"},
        {"统计项": "代理费用金额占比", "数值": float(fills.loc[fills["fee_is_proxy"].astype(bool), "commission"].sum() / fills["commission"].sum()), "说明": "按客户手续费"},
        {"统计项": "拒单及部分成交事件", "数值": int(formal["拒单及部分成交事件"]), "说明": "正式基准"},
        {"统计项": "期末未完成订单", "数值": int(diagnostics["ending_pending_orders"]), "说明": "样本终点截断，未在样本后虚构成交"},
    ])
    _write_both(checks_frame, root / "accounting_reconciliation_v3")
    _write_both(statistics, root / "execution_audit_statistics_v3")
    passed = bool(checks_frame["是否通过"].all() and impact_mismatch == 0)
    print(f"checks={len(checks_frame)} passed={passed}; cross_zero_orders={cross_zero_orders}; complete_roll_dates={complete_roll_dates}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
