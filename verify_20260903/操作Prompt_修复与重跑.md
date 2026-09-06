# 操作 Prompt：修复 + 重跑（一次性执行清单）

> 目标：把 `verify_20260903/重跑结果清单.md` 的 R1–R7 与 `verify_20260903/修改方案文档.md` 的 M1–M9 落地为可执行步骤。
> 交付对象：GLM 的 Zcode。
> **铁律（最高优先级，违反即判失败）**：
> 1. **原仓库 `D:\FiveSectorMomentum` 一个字节都不许改**（`src/` `configs/` `scripts/` `tests/` `data/` `outputs/` `docs/` 全部只读）。本 prompt 所有"改代码/改数据"动作都发生在副本里。
> 2. 每个随机步骤记录 seed；v3 为确定性流程（无 RNG），v4_2 用 bootstrap seed `20260902`（`configs/five_sector_momentum_v4_2_repaired.yaml`）。
> 3. 每项完成后先过**校准门**（先复现"现状正确值"，再切换到修正值），否则不算数。
> 4. 所有新产物写到副本自己的 `outputs/` 或 `rerun_artifacts/`，不得写回原仓库。

---

## Phase 0 — 建立只读副本 + 完整性证明

```powershell
# 0.1 在仓库同级建副本（排除 .git 与 .mimosa，其余全拷）
robocopy D:\FiveSectorMomentum D:\FiveSectorMomentum_rerun /E /XD .git .mimosa /NFL /NDL /NJH /NJS
```
> 若磁盘紧张，可只拷 `src configs scripts tests data docs .env`（v4_2 源引用 `outputs/v4_20260902_102628`、`outputs/v4_1_20260902_163841` 与现有 fills，做 R2/R3 的 S1 复盘时再补拷 `outputs/v4_2_20260903_091241`）。

```powershell
# 0.2 证明原仓库未被触碰（工作树快照 + 关键文件哈希）
cd D:\FiveSectorMomentum
git status --porcelain   # 期望：只有 ?? .mimosa/ ?? audit_20260903*/ ?? verify_20260903/
git rev-parse HEAD       # 期望：093b24a2297711d4d40cd75f3ce1c624eaaf038e
```
> 全程以副本 `D:\FiveSectorMomentum_rerun` 为工作目录（下文记为 `$R`）。**不要**在 `$R` 里 `git init` 或改动原 `.git`。

---

## Phase 1 — P0 代码修复（全部在 `$R` 内，行号以 `$R` 当前源码为准复核）

### M1　费率单位 `/10000` → `/1000`
- 文件：`$R\src\five_sector_momentum\costs_v3.py`
- 改 `:48`：`data["fee_rate"] = data["trading_fee_rate"].fillna(0.0) / 10000.0` → `/1000.0`
- 改 `:157`：`fee_rate_unit` 描述 `"Tushare原值/10000"` → `"/1000"`
- **保留** `:53-60` 的 T 特例（CFFEX 固定 3 元/手误存 rate 字段，已按元/手纠正），**不要动**。
- 验收：仅影响 RB（万1/万3）与 SP（万0.5/万0.2）；固定每手品种（AL/SC/T/RU 等）不变。

### M2　`fut_settle` 下载改逐合约
- 文件：`$R\src\five_sector_momentum\data_source.py`
- `:236-261` `_download_contract_endpoint(...)`：把默认 `batch_size: int = 6` 的**批量逗号拼接调用**改为对 `fut_settle`（及 `ft_limit`）逐合约调用（`batch_size=1`）；空返回/行数不匹配时写入 `manifest["warnings"]` 而非静默。
- 参考已有正确实现：`scripts/download_v3_fee_data.py`（逐合约 `pro.fut_settle(ts_code=contract,...)`，已得 36,040 行）。
- 验收：单合约 RB2410 应返 ~103 行；批量调用 0 行现象消失。

### M3　停板价补全 + 拒单逻辑生效
- 数据侧（二选一）：
  - 高权限 token 拉 `ft_limit`（当前 token 无权限，T2a 已证）；或
  - **推算**：`upper_limit/lower_limit = pre_settle × (1 ± 交易所停板幅度)`，幅度规则按 SHFE/CZCE/DCE/INE/CFFEX 各自连板规则建表，至少覆盖锁板日（`high==low`）。
- 引擎侧：`$R\src\five_sector_momentum\engine_v3.py` `:373`（`reject_locked_limit`）、`:397-400`（上下停板夹取）、`:471-474`（`_is_adverse_limit_at_open`）——补齐 bars 的 `upper_limit/lower_limit` 后**无需改逻辑**即可生效。
- 验收：锁板 12 天中逆停板方向的成交被拒单；拒单清单与 `rejections` 对齐。

---

## Phase 2 — 派生数据重生成（在 `$R`，用修复后的代码）

### D1　费率规则重建（R1 前提，关键）
> `historical_fee_rules.pkl/.csv` 是已生成的持久化产物，**只改 `costs_v3.py` 不会改变引擎读到的旧规则**。必须用修复后的 `/1000` 重建。
```powershell
cd $R
python -c "import sys; sys.path.insert(0,'src'); import pandas as pd; from five_sector_momentum.costs_v3 import build_fee_rules; from five_sector_momentum.storage import read_frame; raw=read_frame('data/v3/fees/tushare_fut_settle_daily_raw'); mapping=read_frame('data/normalized_v2/mapping'); build_fee_rules(raw, mapping, 'data/v3/fees')"
```
- 验收：重建后 RB 规则 `fee_rate ∈ {0.0001,0.0003}`、SP `∈ {0.00005,0.00002}`；T 固定 3 元/手且 `fee_rate=0`。

### D2　真实逐日保证金合入 bars（M4 前置）
- 来源：`data/v3/fees/tushare_fut_settle_daily_raw.pkl`（`long_margin_rate/short_margin_rate` 35,742 非空）。
- 把 `(ts_code, date) → long/short_margin_rate` 合入 normalized bars（复用 `data_pipeline.py:128-153` `_merge_daily_contract_data` 的字段），**T 品种 ÷100 归一**（百分数 2.0=2% 与费率字段漂移同源）。
- 验收：真实率下约束触发日显著下降（v3 商品 67→~2、总 86→~2，见 T3）。

---

## Phase 3 — P0 重跑（R1 / R2 / R3）

### R1　费率修正后的全套正式结果（净利/Sharpe/盈亏平衡）
- 方式 A（主，权威）：`$R` 内重跑 v3：
```powershell
cd $R
python -m five_sector_momentum backtest run --config configs/five_sector_momentum_v3.yaml
```
（v3 复用冻结 normalized 数据，**不要** `--rebuild-data`）
- 方式 B（交叉复核，独立实现，不 import 引擎）：对现有 v4_2 S1/S2 fills 做"后验手续费重算"（`commission = |qty|×(fee_per_lot + price×point_value×fee_rate)`，RB/SP 的 `fee_rate` ×10），再重推 net/equity/Sharpe/盈亏平衡。
- 校准门：修复前先确认"旧口径复算 = 现值"（v3 手续费 1,272,705；S1 3,998,744）。
- **验收锚点**：修正后 v3 手续费 ≈ **+47万**（区间 [47万,49万]，1,272,705→~1,745,313）；S1 ≈ **+140万**（[139万,151万]，3,998,744→~5,396,437）；净利下调 ~1.07%（v3）/1.39%（S1）；盈亏平衡 ~54× → ~52×。结论方向（正收益）不变。

### R2　锁板拒单生效后重跑（剔除幽灵成交）
- `$R` 内，在 M3+D2 完成后重跑 v3 与 v4_2 S1（`python scripts/run_v4_2_repaired.py --phase runs`）。
- 重点核对 **2025-04-07 RU2505 换月旧腿逆跌停卖出（278 手）** 被拒。
- 验收：逆停板成交段归零；逐笔拒单清单与 `rejections` 对齐；极端日（2020-02-03、2021-10-08、2025-04-07）净利/回撤下调。
- 说明：若 v4_2 的 G1/G2 复现门因引擎改动报 fail（其设计目的就是防改动），则 S1/S2 的**权威口径**改用"后验剔除逆停板幽灵成交段 + 重推权益"的方式，并在报告中注明"全链路重跑受复现门阻挡，采用后验影响估计"。

### R3　真实逐日保证金率下约束重估
- `$R` 内重跑 v3，替换静态 `fallback_margin_rate×1.25` 为 D2 合入的真实逐日率。
- 验收：触发日 v3 商品 67→~2、总 86→~2；确认"原结果过度保守"而非"低估风险"。

---

## Phase 4 — P1 重跑（R4 / R5 / R6 / R7，多为独立复算，不改引擎）

### R4　信号层独立复算（唯一未到金标准的链路）
- 从原始 bars + `configs/five_sector_momentum_v4_2_repaired.yaml` 独立实现 `price_diff_sharpe` 评分→周选择→eligibility，与框架 `scores/selections/targets` 逐行对齐。
- 验收：评分方向/入选品种一致；不一致项逐条归因（T8 已证订单→成交链路，本项补订单上游）。

### R5　M1（v1/v2 费用兜底高估 ~57 倍）独立重算
- 独立重算 v1/v2 的 T 逐手费用（207 元 vs 官方 3.6 元），并给 v1/v2 成本结论打"作废/仅方向参考"标注（对应 M9）。

### R6　M2/M3 方法学量化
- ① 冻结样本外期（`sample_split: 2022-01-01` 之后只读一次）重估 21 路胜者显著性；② 真 walk-forward（滚动窗口内重选参数）对比切片展示，量化偏差。
- 对应 M6/M7 的落地验证。

### R7　Panama 百分比口径下游清理
- 全仓检索对 `adjusted_prices`（Panama 复权）的任何 `pct_change`/百分比收益用法，逐处改点差或同号率，或加显式警示（对应 M5）。

---

## Phase 5 — P1/P2 文档与工程修改（在 `$R`，只改副本）

- **M4**：真实保证金合入 bars（T ÷100 归一）——引擎/`data_pipeline.py`。
- **M5**：数据字典/README 声明"Panama 复权序列不可做百分比收益分析"。
- **M6**：`workflow_v4.py` 切片展示改名为"切片敏感性展示"或实现真 walk-forward。
- **M7**：`analytics_v3.py` 验证期 21 路择优→冻结样本外 / 多重比较校正。
- **M8**：依赖锁定（requirements 版本）、输出目录配置化、v3 行序稳定排序、CI + 数据快照哈希。
- **M9**：v1/v2 成本结论打"作废"标注。

---

## Phase 6 — 交付物与证据（写回 `verify_20260903/rerun_artifacts/`，不碰原仓库）

1. `calibration_gates.md`：每个 P0 项的校准门通过记录（旧口径复算 = 现值 → 切换新口径）。
2. `diff_before_after.csv`：R1/R2/R3 的"修正前 vs 修正后"（净利/Sharpe/回撤/费用/触发日）。
3. `rerun_manifest.json`：seed、命令、输入文件哈希、输出路径。
4. `rejections_lock_limit.csv`：R2 逐笔拒单清单。
5. 原仓库完整性复验：跑完后再执行 Phase 0.2，确认原仓库哈希/`git status` 与开始时一致。

---

## 验收总览（一票否决项）
- 原仓库 `git status` 与 `git rev-parse HEAD` 全程不变；关键源文件哈希不变。
- R1 手续费修正幅度落在 [47万,49万](v3)、[139万,151万](S1) 区间，且方向为"净利下调"。
- R2 逆停板成交段归零；RU2505 2025-04-07 旧腿被拒。
- R3 真实率下触发日显著下降，方向为"原结果保守"。
- 每个 P0 项都过了校准门（先复现现状，再切修正）。
