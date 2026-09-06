# R6 — 验证期择优 / 伪 walk-forward 量化（只读复核）

- 复核对象：`D:\FiveSectorMomentum` 原始仓库（只读，未改动任何 `src/configs/scripts/tests/data/outputs/docs` 文件）。
- 新增产物（仅允许写入区）：`rerun_20260903/rerun_artifacts/r6_compute.py`、`rerun_20260903/rerun_artifacts/r6_compute.json`、本文件。
- 环境：Python 3.13.8 / pandas 2.2.3 / numpy 2.2.3（未安装任何新依赖）。

## 0. 先纠正任务命题的一处关键错位（这本身就是审计结论）

**"v4_2 从 21 个候选里用验证期择优出一个 winner" 这一命题与实际代码不符。** 实际链条是：

1. **21 路验证期择优发生在 v4（及 v4.1 的 bootstrap），不在 v4_2。**
   - 21 个经济上不同的基础策略 = `reference_v3_252` + 17 个 v4 正式候选 + 3 个 v4.1 修正袖套；出处 `docs/V4_1_COST_SIGNAL_DIVERSIFICATION_TASK.md:368-375`。
   - v4 的 winner 是 `single_180_skip5`（`outputs/v4_20260902_102628/final_recommendation_v4.csv:2`）。
   - v4.1 事后又把 `single_180_skip5` 降级为"并行挑战者"、保留 `reference_v3_252` 为正式方案（`outputs/v4_1_20260902_163841/recommendation_v4_1.csv:2-6`）。
2. **v4_2 是一个预注册的、固定袖套实验，明确"不新增参数、不择优"。** 它只跑 4 个引擎场景：G1=`single_20_skip5`、G2=`single_250`、S1=`strategy_sleeve_20skip5_250_equal_risk`（C3）、S2=同袖套固定 3 tick（C7），其余 `single_20/60/120/180` 与 `reference_v3_252` 只读引用 v4 旧结果（`docs/V4_2_EXPERIMENT_REGISTRY.md:7-18`、`src/five_sector_momentum/workflow_v4_2.py:161-165`）。

因此 M2/M3 的量化对象应落在 v4 的 `single_180_skip5` 择优过程上；v4_2 的 S1 袖套单独给出验证期读数，但它不是 21 路择优产物。下文把两者分开报告。

---

## 1. 21 路 winner 究竟是怎么选出来的（M2 证据链）

**验证窗口边界**：全样本 2015-01-01 至 2026-08-31；样本内 2015–2021；验证期 2022-01-01 起；2026 为不完整年度。
- `configs/five_sector_momentum_v4_2_repaired.yaml:2` — `run.sample_split: "2022-01-01"`、`end: "2026-08-31"`。
- `docs/V4_2_EXPERIMENT_REGISTRY.md:29` — "样本内2015—2021，验证期2022起；2026是不完整年度"。
- `src/five_sector_momentum/analytics_v4.py:21-45`（`metrics_from_equity`）+ `:81-87`（验证期 = `date >= sample_split`）。

**择优指标 = 验证期夏普（在多门槛之后作为首要业绩排序键）**：
- `src/five_sector_momentum/workflow_v4.py:484-492` — 7 个预注册门槛（样本内/验证期均正、滚动拼接为正、删除 2020/2024 仍正、回撤或 Calmar 改善、成本换手不过度、年份集中不恶化、FG/板块集中不恶化）。
- `src/five_sector_momentum/workflow_v4.py:504-507` — `sort_values(["通过门槛数", "验证期夏普", "删除2020和2024夏普", "Calmar", "年份前二占比", "年化换手"])`，即**验证期夏普是第一业绩排序键**。
- `src/five_sector_momentum/workflow_v4.py:577-607` — 最终推荐在"严格门槛 + 2/3 tick 压力 + 邻近一致性"通过者中，按 `(通过门槛数, 验证期夏普, 删除2020和2024夏普, Calmar)` 降序取 `qualifying[0]` → `single_180_skip5`。

**结论（M2）**：winner 是在同一段 2022–2026 验证期上、对 17 个 v4 候选做多门槛筛选后，再按**验证期夏普**挑出来的。这属于典型的 validation-period optimization + multiple comparisons；2022–2026 在被选时已被反复查看（`docs/v4_1_deep_interpretation_20260902/10_Bootstrap可靠性解读.md:69`）。

---

## 2. 冻结样本外（验证期）量化：winner vs 21 候选分布（方法 3a）

读一次、全 21 策略固定参数下的 2022-01-01→2026-08-31 **含成本净值** 验证期指标（`scenario_metrics_v4.csv` 的 18 个 v4 场景 + `sleeve_metrics_v4_1.csv` 的 3 个 C3 袖套）。全表见 `r6_compute.json`。

**验证期（net）排序表（按 Sharpe 降序，前 6 名）**

| 名次 | 策略 | 验证期 CAGR | 验证期 Sharpe | 验证期 MDD |
|---|---|---|---|---|
| 1 | `single_250_minus_20` | 20.44% | **0.9487** | -33.33% |
| 2 | `single_250` | 15.83% | 0.7728 | -30.99% |
| 3 | `reference_v3_252`（正式基准） | 14.43% | 0.7196 | -32.25% |
| **4** | **`single_180_skip5`（v4 winner）** | **12.54%** | **0.6556** | **-35.47%** |
| 5 | `single_250_skip5` | 11.18% | 0.5931 | -28.10% |
| 6 | `single_180` | 8.42% | 0.4778 | -42.49% |

（完整 21 行排序见 `r6_compute.json`；后 10 名 Sharpe 均为负或接近 0，最低 `single_60_skip5` = -0.8526。）

**精确数值（脚本复算，`r6_compute.json`）**

- winner `single_180_skip5` 验证期：CAGR = **+12.54%**，Sharpe = **0.6556**，MDD = **-35.47%**。
- 验证期 Sharpe 名次 = **4 / 21**（约 81 分位）；验证期 CAGR 名次 = **4 / 21**。
- 21 策略验证期 Sharpe：中位数 = **0.2110**，均值 = **0.1573**，标准差 = **0.4722**。
- winner 超出中位 Sharpe = **+0.4446**；超出均值 = **+0.4983**。
- winner 超出中位 CAGR = **+10.32 pp**；超出均值 = **+11.07 pp**。
- **关键事实**：验证期 Sharpe 的点估计冠军是 `single_250_minus_20`（0.9487），**不是**被选中的 winner；winner 排在正式基准 `reference_v3_252`（0.7196）**之后**。即 winner 之所以当选，靠的是"多门槛筛掉 250_minus_20 后再比验证期夏普"，而非在全部 21 个候选里拿第一。

**多重比较零假设检验（经典 max-of-n 参照）**

把 21 个验证期 Sharpe 标准化后，问"从 21 个无真实差异的策略里挑最高者，最高值会多大"：

- 观测到的最佳（`single_250_minus_20`）标准化值 `z_max = (0.9487 - 0.1573)/0.4722 = 1.676`。
- 21 个 iid 标准正态的期望最大值 = **1.888**（200k 次 Monte Carlo，seed 20260902）；其 **95 分位 = 2.816**。
- winner 自身 `z_winner = 1.055`。

**即：连"21 个候选里的第一名"的标准化优势（1.676）都低于纯噪声下 21 选 1 的期望最大值（1.888），更远低于其 95 分位（2.816）。** 因此即便用单边 α=5% 也无法拒绝"21 个候选在验证期 Sharpe 上无真实差异"的原假设；观察到的 21 路冠军完全落在多重比较的噪声分布之内，不能用验证期点估计支持任何"显著优胜"。

**2000 次联合移动分块 Bootstrap（winner vs 21 候选横截面中位数，方法 3a 的 bootstrap 部分）**

来源 `outputs/v4_1_20260902_163841/bootstrap_strategy_draws_v4_1.csv`（phase=validation, basis=net，21 策略同日期区块配对抽样）：

- winner Sharpe 分布：均值 **0.710**，中位 **0.709**，90% 区间 **[0.016, 1.379]**。
- winner − 21 策略中位数 Sharpe：均值 **+0.522**，中位 **+0.513**，90% 区间 **[-0.146, +1.253]**，`P(gap>0)=88.8%`。
- winner 在 21 策略中的 Bootstrap 平均名次 = **5.26 / 21**（中位名次 4），比点估计的 4/21 还略滑落。

**但要区分两个不同问题**：

1. winner 显著高于 21 个候选的**中位数**（88.8% 次数）——这是真的，因为 21 个候选里有一大半在验证期为负/接近零，中位数只有 0.211。
2. winner 是否显著优于**需要替换的基准 `reference_v3_252`**（真正决策问题）——几乎五五开。配对 Bootstrap：验证期 Sharpe 差均值 **+0.015**、中位 **+0.021**、`P(diff>0)=51.65%`、95% 区间 **[-0.978, +0.987]**（`docs/v4_1_deep_interpretation_20260902/10_Bootstrap可靠性解读.md:37-41`）。验证期 CAGR 差 `P(diff>0)=50.70%`。

**冠军保持率（排名不稳定性）**：验证期 Sharpe 点估计冠军 `single_250_minus_20` 在 2000 次 bootstrap 中仅 **39.25%** 次数保住第一；验证期 CAGR 冠军保持率 **40.25%**（`outputs/v4_1_20260902_163841/bootstrap_point_winner_stability_v4_1.csv:10-11`）。这直接支持"点估计冠军强烈依赖历史月份排列"。

---

## 3. M3：现在的"walk-forward"是切片展示，不是真 walk-forward（证据链）

- `src/five_sector_momentum/analytics_v4.py:148-171` — `rolling_walk_forward_v4` 对**同一个已跑完的 `result.equity`** 按 5 年训练/1 年测试切年份窗口，逐窗用 `metrics_from_equity` 重算指标；**没有任何在窗口内重新择参/重新选策略的动作**。
- `src/five_sector_momentum/analytics_v4_2.py:206-209` — v4_2 的 `walk_forward` 行显式标注 `selection='固定策略、不按训练收益择优'`，另加一行 `selection='2020起既有固定运行拼接'`（stitched）。这是作者主动披露的"固定策略切片"，不是重择参 walk-forward。
- `docs/V4_2_EXPERIMENT_REGISTRY.md:65` — "不以全样本最高收益筛选…通过也仅列'并行观察候选'，不称干净样本外证明"。

**M3 结论成立**：现有 `rolling_walk_forward_v4` / `walk_forward_v4_2` 是"固定参数在连续年份切片上的稳健性展示"，参数从未在滚动窗口内被重新选择，不能称为 true walk-forward。

**真 walk-forward 是否可在此实现（方法 3b）**：**不可行**，理由：

1. 真 walk-forward 需要在每个滚动/扩展窗口内，对每个候选重新估计信号并重跑交易引擎（头寸、成本、约束全部要因果重算）。框架的引擎是按"完整历史、单一场景"运行的（`BacktestEngineV4`/`SleeveEngineV42`），没有"窗口内再训练+换参再跑"的现成入口。
2. v4_2 注册表硬性规定本轮新增历史引擎运行最多 4 次（`docs/V4_2_EXPERIMENT_REGISTRY.md:9`），且已全部用于 G1/G2/S1/S2；重新择参需要 21 候选 × 多窗口次引擎运行，超出注册约束。
3. 本复核是只读验证，禁止改动任何源文件，也无法合法发起新一轮引擎重跑。

因此 **3a（冻结验证期读一次 + 21 候选分布 + 联合 bootstrap）就是本任务能给出的最佳、且被框架自身底表支持的选择偏差估计**，已在上节给出。未用任何"假 re-selection"伪造真 walk-forward 数字。

---

## 4. v4_2 固定袖套本身的验证期读数（附带，非 21 路 winner）

v4_2 唯一新增投资方案 S1 的验证期（2022-01-01→2026-08-31，net）：

- `strategy_sleeve_20skip5_250_equal_risk`（S1，C3）：CAGR **+16.58%**，Sharpe **0.8079**，MDD **-34.35%**（`outputs/v4_2_20260903_091241/scenario_metrics_v4_2.csv:10`）。
- 压力版 S2（固定 3 tick）：CAGR **+9.86%**，Sharpe **0.5372**，MDD **-36.91%**（同文件 `:13`）。
- 组成 G1 `single_20_skip5`：CAGR 5.40%、Sharpe 0.3457（`:4`）；G2 `single_250`：CAGR 15.83%、Sharpe 0.7728（`:7`）。

如果把 S1 的 Sharpe 0.8079 放进上表 21 策略，它排 **2/22**（仅次于 `single_250_minus_20` 0.9487）。但注意两点：S1 是**预注册固定 50/50 风险袖套**、不是从 21 路里择优出来的（`docs/V4_2_EXPERIMENT_REGISTRY.md:7-18`）；其验证期仍是 2022–2026 这段已被 v4 反复查看的区间，**不构成干净样本外证明**（`docs/V4_2_EXPERIMENT_REGISTRY.md:65`、`docs/v4_1_deep_interpretation_20260902/README.md:33`）。

---

## 5. 最终结论

1. **M2（验证期择优 + 多重比较）成立且已被现有底表证实。** v4 的 winner `single_180_skip5` 是在同一验证期上按"门槛数 + 验证期夏普"选出的（`workflow_v4.py:504-507, 603-607`）。它在 21 个基础策略里验证期 Sharpe 仅排 **4/21**，落后于基准 `reference_v3_252` 和 `single_250_minus_20`；相对 21 候选中位 Sharpe 超出 **+0.4446**，但：
   - 对"是否优于 v3 基准"的配对 bootstrap 只是 **51.65%** 五五开（95% CI 跨零 [-0.978, +0.987]）；
   - 21 选 1 的点估计冠军 `single_250_minus_20` 的标准化优势 z=1.676 **低于**纯噪声下 21 选 1 的期望最大值 1.888；
   - 验证期 Sharpe 冠军的 bootstrap 保持率仅 **39.25%**。
   → **"winner 是多重比较的产物"这一结论成立**：观察到的 21 路冠军强度不足以区别于噪声，更不足以支持"显著优于 v3"。

2. **M3（伪 walk-forward）成立。** `rolling_walk_forward_v4` / `walk_forward_v4_2` 是固定参数切片（`analytics_v4.py:148-171`、`analytics_v4_2.py:206-209`，后者自标"固定策略、不按训练收益择优"），参数未在窗口内重选，不是 true walk-forward。真 walk-forward 在本只读复核下不可行（需逐窗口全引擎重跑，且 v4_2 注册表最多 4 次引擎运行已用尽）。

3. **对 v4_2 自身**：S1 固定袖套验证期 Sharpe 0.8079 / CAGR 16.58% 是较稳健的读数，但它是预注册固定设计（非 21 路择优），且 2022–2026 不是干净样本外；其"显著优于基准"同样未在干净样本外上被证明。

## 6. 可复现产物

- `rerun_20260903/rerun_artifacts/r6_compute.py` — 复算脚本（只读仓库 + 只写 rerun_artifacts）。
- `rerun_20260903/rerun_artifacts/r6_compute.json` — 21 策略验证期全表 + 点估计/bootstrap 汇总。
- 关键输入（未改动，只读）：`outputs/v4_20260902_102628/scenario_metrics_v4.csv`、`outputs/v4_1_20260902_163841/sleeve_metrics_v4_1.csv`、`outputs/v4_1_20260902_163841/bootstrap_strategy_draws_v4_1.csv`、`outputs/v4_1_20260902_163841/bootstrap_point_winner_stability_v4_1.csv`、`outputs/v4_2_20260903_091241/scenario_metrics_v4_2.csv`。
