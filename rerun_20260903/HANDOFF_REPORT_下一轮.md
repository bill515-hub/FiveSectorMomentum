# 修复+重跑 · 阶段交接文档（下一轮操作手册）

> 生成时间：本轮（人工叫停后）
> 任务目标：执行 `操作Prompt_修复与重跑.md`，在只读副本中落地 M1–M9 代码修复与 R1–R7 重跑。
> 铁律：原仓库 `D:\FiveSectorMomentum` 已有代码/结果/文档**零改动**；所有产出只落在新建目录。

---

## 0. 铁律遵守状态（已复核）

`git -C D:\FiveSectorMomentum status --short` 输出仅 5 条**未跟踪目录**，**无任何已跟踪文件的修改(M)/删除(D)**：

```
?? .mimosa/
?? audit_20260903/
?? audit_20260903_v2/
?? rerun_20260903/
?? verify_20260903/
```

结论：原仓库受 git 跟踪的既有文件保持字节级不变；新增均为独立目录。

工作副本目录：`D:\FiveSectorMomentum\rerun_20260903\`（下称 `rerun/`）。

---

## 1. 运行环境与命令

- Python 3.13.8，pandas 2.2.3。
- 环境变量：`PYTHONPATH=D:\FiveSectorMomentum\rerun_20260903\src`。
- 运行目录：`D:\FiveSectorMomentum\rerun_20260903`。
- 回测命令：
  `python -m five_sector_momentum backtest run --config configs/five_sector_momentum_v3.yaml`
- **沙箱说明**：`pwsh` 的 workspace-write 后端曾因临时目录缺失而失效
  （`windows-acl-run: --temp is not an existing directory: C:\Users\78763\AppData\Local\Temp\dsh-2NyxDb`）。
  本轮已通过在该目录写入 `probe.txt` 恢复（`Test-Path` 返回 True，pwsh 可正常只读执行）。
  **danger-full-access 升级此前已被用户拒绝，后续不要再升级该模式**；只读 pwsh 与 write/edit/read/grep/glob 工具链均可用。

---

## 2. 已完成工作

### 2.1 代码修复（已在 `rerun/src/five_sector_momentum/` 落地）
- **M1（费率单位 H2）**：`costs_v3.py` 第 48 行 `/1000.0`、第 157 行单位串 `/1000`（原 `/10000`，RB/SP 手续费被低估 10 倍）。T 特例保留。
- **M2（逐合约查询 H1）**：`data_source.py` 对 `fut_settle`/`ft_limit` 用 `batch_size=1`。
- **M4（保证金回退语义）**：`engine.py` 第 545 行 `base_rate = reported if reported > 0 else fallback`（原 `max(reported, fallback)`，导致真实低保证金率被静态值压高）。

### 2.2 R1（费率修正重跑）——数值已完成，报告未补
v3 修正后正式情景数值（已捕获）：
| 指标 | 修正后 | 原始 |
|---|---|---|
| 手续费 | 1,715,216.14 | 1,272,704.65 |
| 净利润 | 43,694,213.86 | 45,639,975.35 |
| 手数 | 407,319 | 417,534 |

⚠️ **未闭环**：`BACKTEST_RESULT_REPORT_v3.md` 生成时崩溃（`reports_v3.py:189` 的
`KeyError: '统计项'`），因为 `execution_audit_statistics_v3.csv` 是后置步骤产物、跑批时未生成。
**修复路径**：回测跑完后先执行 `scripts/audit_v3_outputs.py` 与 `scripts/finalize_v3_outputs.py`，
再重新生成报告。

### 2.3 R4（v4_2 信号层独立复算）——完成，逐比特一致
后台子代理 `b0a46efb` 用纯 pandas/numpy 重实现整条流水线，与既有产物外层合并比对：
- `scores.pkl` 52,343 行，max_abs_diff = 0.0，符号一致 100%，NaN warmup 掩码逐位对齐；
- `selections.pkl`（8,112/4,188/3,924 行）direction+score 100% 一致；
- `targets.pkl`（21,402/18,502/18,638 行）optimal_position/buffered_target/nrd/emergency 100% 一致；
- 结论：**零差异，全通过**。产物在 `rerun/rerun_artifacts/r4_*`。

---

## 3. 进行中：R2 锁板拒单（本轮主线，含新用户规则）

### 3.1 已确认的两处根因
- **H1**：`fut_settle`/`ft_limit` 返回 0 行 → bars 缺 `upper_limit`/`lower_limit`/`long_margin_rate`
  → `reject_locked_limit` 永不触发，保证金回退静态值 ×1.25。
- **H2**：费率单位千分之几，代码除 `/10000` 而非 `/1000`（M1 已修）。

### 3.2 锁板口径（审计真值）
- **主力映射口径**：`high==low & vol>0` 的锁板日 = **12 天**。
- **全合约口径**额外浮现 RU2505 2025-04-07 **旧腿**跌停卖出（174 手 / 278 手）。
- 引擎已有重试：`_execute_order_v3` 返回拒单 + `attempts`；`unfilled_modes=[cancel_recalculate]`；fills 带 `attempt`（最多重试 11 天）。

### 3.3 M3 初版脚本已报废（勿再用）
`rerun/rerun_artifacts/derive_limit_prices.py`：对所有合约用 `high==low & vol>0` →
误判 16,902 个"锁板日"（8001 涨 / 7970 跌）vs 真值 12。且 exit 1（broken pipe）导致
`to_pickle` 未执行 —— **已核实 `bars.pkl` 未被污染**（597,541 行 × 20 列，无 upper/lower_limit 列）。
`bars_pristine.pkl` 备份哈希 = 原始（E96D15B1…C6644E1，match=True）。

### 3.4 新用户规则（本轮最新指令，已确认口径）
用户指令原文：**"涨停板可以第二天再交易，如果是农产品和能源化工，可以交易排名靠后的一个品种"**。

澄清问答结果：
- **机制（Q2，已选定）**：绝对板块（RB/T/AL）→ 顺延到下一交易日；截面板块（农产品、能源化工）→ 换该板块**排名靠后的品种**（次优）。
- **跌停卖出侧（Q1，自定义）**：**"2、3 可以分别测试，对比结果"** → 跑两个场景并对比：
  - 场景 2（对称）：跌停卖出也顺延次日再交易；
  - 场景 3（拒单）：跌停卖出直接拒单（不引入次日/替换）。

最终落地设计（已写入 `rerun/rerun_artifacts/lockboard_defer_substitute_design.md`）：
1. 涨停买入被挡：
   - 绝对板块 → 同一订单顺延到下一交易日开盘；
   - 截面板块 → 换该板块次优品种（第 2 高分），重新按次优品种自身波动率定规模；
2. 跌停卖出被挡：**两个场景分别跑并对比**（对称顺延 vs 直接拒单）。

### 3.5 本轮新写但未运行的脚本
- `rerun/rerun_artifacts/diagnose_locked_days.py`（**只报告不写盘**）：按三种口径统计锁板日，
  校验"主力映射=12、全合约=12+RU2505 旧腿"。**尚未成功运行**（上次 pwsh 被中断，无结果落盘）。

---

## 4. 未完成任务清单

| 编号 | 内容 | 状态 |
|---|---|---|
| R1 | 报告 .md 补生成（先跑 `audit_v3_outputs.py`+`finalize_v3_outputs.py`） | 数值已得，报告未闭环 |
| R2 | 锁板 M3 正确重写 + 引擎"顺延次日/截面换次优" + 跌停两场景对比 | **进行中（本轮主线）** |
| R3 | 真实保证金：跑 `merge_margin_into_bars.py`（D2）后重跑 v3；预期触发天数 67→2（商品）/86→2（合计） | 未开始 |
| R7 | Panama `pct_change` 发现报告（已 grep：仅 `analytics.py:30` 用 `pct_change`，作用在净值而非复权价） | 未写报告 |
| M5–M9 | 文档/工程化修改 | 未开始 |
| 阶段6 | `calibration_gates.md`、`diff_before_after.csv`、`rerun_manifest.json`、`rejections_lock_limit.csv`、原仓库复核 | 未开始 |

---

## 5. 关键数值锚点（勿重算，直接引用）

- v3 修正正式：手续费 1,715,216.14 / 净利润 43,694,213.86 / 手数 407,319。
- v3 原始：手续费 1,272,704.65 / 净利润 45,639,975.35 / 手数 417,534。
- S1 客户手续费 3,998,744。
- R4 精确复现：52,343 评分逐比特一致；S1 终值 118,575,796.34。
- R5：v1/v2 T 手续费约 57× 高估（回退 `max(lots*5, lots*price*pv*0.0002)`）。
- R6：胜者 `single_180_skip5` = 多重比较伪象（最佳 z=1.676 < 1.888）。

---

## 6. 下一轮建议执行顺序

1. **先补 R1 闭环**（最快可见交付）：跑 `audit_v3_outputs.py` → `finalize_v3_outputs.py` → 重生成报告。
2. **R2 主线**：
   a. 运行 `diagnose_locked_days.py` 锁定 12+RU2505 真值；
   b. 重写 M3：仅对"引擎可持有合约"（主力映射各日期合约 + 换月旧腿）做 `high==low & vol>0` 推断，
      涨板设 `upper_limit=settlement`、跌板设 `lower_limit=settlement`，其余 NaN；
   c. 引擎改 `engine_v3.py`：`_execute_order_v3` 中把 `adverse_limit_at_open` 硬拒单改为
      "绝对→顺延次日 / 截面→换次优"，跌停卖出侧加场景开关（对称顺延 vs 拒单）；
   d. 记录种子，重跑 v3，对比两场景，核对 RU2505 2025-04-07 旧腿 278 手卖出的处理结果。
3. **R3**：跑 `merge_margin_into_bars.py`（D2）→ 重跑 v3 → 捕获触发天数。
4. **R7**：写 Panama `pct_change` 发现报告（结论已在 §4）。
5. **阶段6**：汇总校准门记录与前后对照表。

---

## 7. 关键文件路径速查

- 副本根：`D:\FiveSectorMomentum\rerun_20260903\`
- 引擎（改锁板逻辑处）：`rerun/src/five_sector_momentum/engine_v3.py`（`_execute_order_v3` 361–474、`_is_adverse_limit_at_open` 469–475）
- 成本：`rerun/src/five_sector_momentum/costs_v3.py`
- 数据下载：`rerun/src/five_sector_momentum/data_source.py`
- 报告崩溃点：`rerun/src/five_sector_momentum/reports_v3.py:189`
- 后置审计：`rerun/scripts/audit_v3_outputs.py`、`rerun/scripts/finalize_v3_outputs.py`
- 配置：`rerun/configs/five_sector_momentum_v3.yaml`（`reject_locked_limit: true` 第 83 行）
- 设计笔记：`rerun/rerun_artifacts/lockboard_defer_substitute_design.md`
- 诊断脚本：`rerun/rerun_artifacts/diagnose_locked_days.py`
- 数据：`rerun/data/normalized_v2/bars.pkl`（未污染）、`bars_pristine.pkl`（备份，hash 匹配）
