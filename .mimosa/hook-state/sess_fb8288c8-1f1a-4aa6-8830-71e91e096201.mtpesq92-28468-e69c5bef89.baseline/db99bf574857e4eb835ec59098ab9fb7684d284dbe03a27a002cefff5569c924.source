from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .storage import read_frame, write_frame


TUSHARE_SETTLE_URL = "https://tushare.pro/document/2?doc_id=141"
CFFEX_FEE_URL = "https://www.cffex.com.cn/cn/zjssf/20240701/39212.html"
INE_SC_FEE_URL = "https://www.ine.cn/publicnotice/notice/202606/t20260623_832254.html"


@dataclass(frozen=True)
class FeeCharge:
    exchange_fee: float
    client_fee: float
    fee_per_lot: float
    fee_rate: float
    rule_id: str
    source_type: str
    source_url: str
    is_proxy: bool


def build_fee_rules(
    raw: pd.DataFrame, mapping: pd.DataFrame, output_root: str | Path | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compress Tushare daily parameters into auditable effective-date rules.

    Tushare supplies opening/non-intraday-close exchange fees by real contract
    and date.  Its optional offset_today_fee field is absent in this dataset.
    We therefore copy the ordinary fee as an explicit close-today proxy, except
    T and SC where current official exchange notices state close-today is free.
    Applying those latest standards backward is still marked as proxy history.
    """
    data = raw[raw.get("source_status", pd.Series(index=raw.index, dtype=str)).eq("tushare")].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data[data["trade_date"].notna()].copy()
    for column in ["trading_fee", "trading_fee_rate", "offset_today_fee"]:
        data[column] = pd.to_numeric(data.get(column, 0.0), errors="coerce")
    data["fee_per_lot"] = data["trading_fee"].fillna(0.0)
    # Tushare expresses this field as the number of ten-thousandths.
    data["fee_rate"] = data["trading_fee_rate"].fillna(0.0) / 10000.0
    data["unit_correction"] = ""
    # Historical T rows place the official 3 yuan/lot value in the rate field
    # while newer rows place it in trading_fee.  CFFEX's official table proves
    # the economic unit is per lot, so correct this documented schema drift.
    t_fixed = (
        data["instrument"].eq("T")
        & data["trading_fee"].isna()
        & data["trading_fee_rate"].gt(0)
    )
    data.loc[t_fixed, "fee_per_lot"] = data.loc[t_fixed, "trading_fee_rate"]
    data.loc[t_fixed, "fee_rate"] = 0.0
    data.loc[t_fixed, "unit_correction"] = "T早期字段单位纠正：官方3元/手"
    data = data.sort_values(["requested_contract", "trade_date"])

    rows: list[dict[str, Any]] = []
    for (contract, instrument), group in data.groupby(["requested_contract", "instrument"]):
        group = group.sort_values("trade_date").copy()
        state = group[["fee_per_lot", "fee_rate"]].round(12)
        group["state_group"] = state.ne(state.shift()).any(axis=1).cumsum()
        pieces = []
        for _, piece in group.groupby("state_group"):
            pieces.append({
                "effective_from": piece["trade_date"].min(),
                "last_observed": piece["trade_date"].max(),
                "fee_per_lot": float(piece["fee_per_lot"].iloc[-1]),
                "fee_rate": float(piece["fee_rate"].iloc[-1]),
                "exchange": str(piece.get("exchange", pd.Series([""])).iloc[-1]),
                "unit_correction": str(piece.get("unit_correction", pd.Series([""])).iloc[-1]),
            })
        for index, piece in enumerate(pieces):
            effective_to = (
                pieces[index + 1]["effective_from"] - pd.Timedelta(days=1)
                if index + 1 < len(pieces) else piece["last_observed"]
            )
            for trade_type in ["open", "close_non_today"]:
                rows.append(_rule_row(
                    contract, instrument, piece["exchange"], piece["effective_from"], effective_to,
                    trade_type, piece["fee_per_lot"], piece["fee_rate"],
                    "tushare_historical", TUSHARE_SETTLE_URL, False,
                    "Tushare逐真实合约每日结算参数；开仓与非日内平仓采用同一交易费。"
                    + (f" {piece['unit_correction']}；核对来源：{CFFEX_FEE_URL}" if piece["unit_correction"] else ""),
                ))
            close_per_lot, close_rate = piece["fee_per_lot"], piece["fee_rate"]
            source_url = TUSHARE_SETTLE_URL
            note = "offset_today_fee字段为空；代理为同期普通交易费。"
            source_type = "proxy_same_as_open"
            if instrument == "T":
                close_per_lot, close_rate = 0.0, 0.0
                source_url = CFFEX_FEE_URL
                source_type = "proxy_latest_official"
                note = "中金所当前标准平今免收；历史缺失，向前回填并明确标记代理。"
            elif instrument == "SC":
                close_per_lot, close_rate = 0.0, 0.0
                source_url = INE_SC_FEE_URL
                source_type = "proxy_latest_official"
                note = "上期能源当前标准平今免收；历史缺失，向前回填并明确标记代理。"
            rows.append(_rule_row(
                contract, instrument, piece["exchange"], piece["effective_from"], effective_to,
                "close_today", close_per_lot, close_rate, source_type, source_url, True, note,
            ))

    rules = pd.DataFrame(rows)
    # Instrument-level proxy handles contracts/dates where Tushare returned no
    # settlement parameter.  It uses the latest available observation, never a
    # fabricated historical exchange rule.
    proxy_rows: list[dict[str, Any]] = []
    for instrument in sorted(mapping["instrument"].unique()):
        subset = data[data["instrument"].eq(instrument)].sort_values("trade_date")
        if subset.empty:
            per_lot, rate, exchange = 0.0, 0.0, ""
            note = "Tushare无任何可用费用行；零交易所费仅用于显式缺失审计，不作为真实数据。"
        else:
            last = subset.iloc[-1]
            per_lot, rate = float(last["fee_per_lot"]), float(last["fee_rate"])
            exchange = str(last.get("exchange", ""))
            note = "合约/日期缺失时采用该品种最新Tushare标准，明确标记代理。"
        for trade_type in ["open", "close_non_today", "close_today"]:
            p, r = per_lot, rate
            source_url = TUSHARE_SETTLE_URL
            if trade_type == "close_today" and instrument in {"T", "SC"}:
                p, r = 0.0, 0.0
                source_url = CFFEX_FEE_URL if instrument == "T" else INE_SC_FEE_URL
            proxy_rows.append(_rule_row(
                "*", instrument, exchange, pd.Timestamp("1900-01-01"), pd.Timestamp("2099-12-31"),
                trade_type, p, r, "proxy_latest_instrument", source_url, True, note,
            ))
    rules = pd.concat([rules, pd.DataFrame(proxy_rows)], ignore_index=True)
    rules.insert(0, "rule_id", [f"FEE-{index:06d}" for index in range(1, len(rules) + 1)])
    rules = rules.sort_values(["instrument", "contract", "trade_type", "effective_from"]).reset_index(drop=True)
    coverage = audit_fee_coverage(rules, mapping)
    if output_root is not None:
        target = Path(output_root)
        target.mkdir(parents=True, exist_ok=True)
        write_frame(rules, target / "historical_fee_rules")
        rules.to_csv(target / "historical_fee_rules.csv", index=False, encoding="utf-8-sig")
        coverage.to_csv(target / "fee_rule_coverage.csv", index=False, encoding="utf-8-sig")
    return rules, coverage


def _rule_row(
    contract: str, instrument: str, exchange: str, start: pd.Timestamp, end: pd.Timestamp,
    trade_type: str, fee_per_lot: float, fee_rate: float, source_type: str,
    source_url: str, is_proxy: bool, notes: str,
) -> dict[str, Any]:
    return {
        "contract": contract, "instrument": instrument, "exchange": exchange,
        "effective_from": pd.Timestamp(start), "effective_to": pd.Timestamp(end),
        "trade_type": trade_type, "fee_per_lot": fee_per_lot, "fee_rate": fee_rate,
        "fee_rate_unit": "成交金额比例（Tushare原值/10000）",
        "source_type": source_type, "source_url": source_url,
        "announcement_date": pd.NaT, "is_proxy": bool(is_proxy), "notes": notes,
    }


def audit_fee_coverage(rules: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    exact = rules[rules["contract"].ne("*") & rules["trade_type"].eq("open")]
    rows = []
    for instrument, group in mapping.groupby("instrument"):
        exact_group = exact[exact["instrument"].eq(instrument)]
        left = group[["date", "contract"]].reset_index(drop=True).reset_index(names="mapping_row")
        joined = left.merge(
            exact_group[["contract", "effective_from", "effective_to"]], on="contract", how="left"
        )
        covered = int(joined.loc[
            joined["date"].ge(joined["effective_from"])
            & joined["date"].le(joined["effective_to"]), "mapping_row"
        ].nunique())
        rows.append({
            "instrument": instrument, "mapping_days": len(group),
            "exact_tushare_days": covered, "proxy_days": len(group) - covered,
            "exact_coverage_ratio": covered / len(group),
        })
    return pd.DataFrame(rows)


class FeeSchedule:
    def __init__(self, rules: pd.DataFrame):
        self.rules = rules.copy()
        self.rules["effective_from"] = pd.to_datetime(self.rules["effective_from"])
        self.rules["effective_to"] = pd.to_datetime(self.rules["effective_to"])
        self._groups = {
            key: group.sort_values("effective_from")
            for key, group in self.rules.groupby(["contract", "instrument", "trade_type"])
        }

    @classmethod
    def load(cls, path_without_suffix: str | Path) -> "FeeSchedule":
        return cls(read_frame(path_without_suffix))

    def charge(
        self, contract: str, instrument: str, date: pd.Timestamp, trade_type: str,
        lots: int, price: float, point_value: float, client_multiplier: float,
    ) -> FeeCharge:
        row = self._lookup(contract, instrument, pd.Timestamp(date), trade_type)
        exchange_fee = abs(lots) * (
            float(row["fee_per_lot"]) + price * point_value * float(row["fee_rate"])
        )
        return FeeCharge(
            exchange_fee=exchange_fee,
            client_fee=exchange_fee * client_multiplier,
            fee_per_lot=float(row["fee_per_lot"]), fee_rate=float(row["fee_rate"]),
            rule_id=str(row["rule_id"]), source_type=str(row["source_type"]),
            source_url=str(row["source_url"]), is_proxy=bool(row["is_proxy"]),
        )

    def _lookup(
        self, contract: str, instrument: str, date: pd.Timestamp, trade_type: str
    ) -> pd.Series:
        for key in [(contract, instrument, trade_type), ("*", instrument, trade_type)]:
            group = self._groups.get(key)
            if group is None:
                continue
            matched = group[group["effective_from"].le(date) & group["effective_to"].ge(date)]
            if not matched.empty:
                return matched.iloc[-1]
        raise KeyError(f"No fee rule for {contract} {instrument} {date.date()} {trade_type}")
