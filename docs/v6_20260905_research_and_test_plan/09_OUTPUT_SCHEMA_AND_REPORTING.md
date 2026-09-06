# v6 输出目录、底层数据和中文报告规范

## 1. 唯一输出目录

每次尝试使用：

```text
outputs/v6_<YYYYMMDD_HHMMSS>_<run_nonce>/
```

目录创建后不复用、不覆盖。根部写：

```text
RUN_STATUS.json
manifest.json
resolved_config.yaml
experiment_registry_snapshot.md
machine_registry_snapshot.yaml
code_inventory.csv
input_hashes.csv
dependency_lock.txt
test_results.xml
test_results.txt
```

`RUN_STATUS.status` 只能是：`RUNNING`、`FAILED_GATE`、`INTERRUPTED`、`PROVISIONAL`、`COMPLETE_NONCANONICAL`、`COMPLETE_CANONICAL`。具体失败原因不编码进 status；失败时另填 `failed_gate_id`、`failure_code` 和 `failure_message`。

层级不得混用：`scenario_status` 使用 `REGISTERED/RUNNING/EFFECTIVE/FAILED/ACCOUNTING_FAILED/INTERRUPTED/REUSED`；E 组的 `family_status` 使用 `NOT_STARTED/RUNNING/COMPLETE/INCOMPLETE_FAMILY`。任一场景 `ACCOUNTING_FAILED` 或强制家族 `INCOMPLETE_FAMILY` 都会使顶层 `RUN_STATUS.status=FAILED_GATE`，并填写相应 `failed_gate_id`；它们本身不是合法顶层状态。

## 2. 推荐目录结构

```text
outputs/v6_<id>/
  00_registry/
  01_data_audit/
  02_reproduction_gates/
  03_correction_ladder/
  04_corrected_strategies/
  05_execution_policy/
  06_statistical_audit/
  07_accounting/
  08_reports/
  09_tests/
  scenarios/<scenario_id>/
```

每个场景目录独立保存参数、状态和底层表。汇总目录只能读取场景目录，不可重新计算另一套口径。

## 3. 每场景强制底层表

| 文件基名 | 作用 |
|---|---|
| `scenario_parameters` | 场景全部解析后参数和角色 |
| `scores` | forecast 及各周期组成 |
| `eligibility` | 流动性、上市、历史窗口资格 |
| `selections` | 横截面选择、绝对方向、runner-up |
| `directions` | 最终信号方向 |
| `internal_sleeve_targets` | 每袖套固定风险目标 |
| `net_target_stages` | 净额、缩放前流动性/OI 预限额、组合/实现波动缩放、正常 buffer、最终流动性/OI 复检及保证金/杠杆硬约束各阶段 |
| `orders` | 真实订单及父目标 |
| `fills` | 成交价、数量、交易类型、费用规则 |
| `rejections` | 拒单、过期、部分成交剩余量和原因 |
| `positions` | 逐日真实合约持仓 |
| `daily_equity` | 毛/净盈亏、权益和回撤 |
| `pnl_by_instrument` | 品种贡献 |
| `pnl_by_sector` | 板块贡献 |
| `pnl_by_side` | 多空贡献 |
| `cost_attribution` | 手续费、基础/换月/冲击滑点 |
| `turnover_attribution` | 按原因码换手 |
| `margin_and_leverage` | 逐日占用、杠杆和约束 |
| `margin_breach_and_insolvency` | 65%/78% 目标约束、日终实际超限、下一目标降险和 `ACCOUNT_INSOLVENT` 停止事件 |
| `buffer_statistics` | buffer 评估/拦截和金额 |
| `event_ledger` | 全部不可变事件 |
| `accounting_reconciliation` | 独立勾稽 |
| `data_lineage_used` | 实际用到的数据/规则来源 |

所有 DataFrame 同时保存 `.csv` 和 `.pkl`。两种格式必须按固定主键排序且逐值一致。空结果也要保留 schema，不得写成无列空文件。每张表另存按 `03_CANONICAL_DATA_AND_CALENDAR_PLAN.md` 的 `canonical_json_rows_v1` 生成的 `table_content_hash`；CSV/pickle 各自文件 SHA 只校验文件完整性，不能用 pickle 字节哈希判断跨环境内容相同。

## 4. 汇总底层表

至少输出：

- `scenario_registry_status.csv/.pkl`；
- `scenario_metrics_full_insample_validation.csv/.pkl`；
- `annual_metrics.csv/.pkl`；
- `monthly_returns.csv/.pkl`；
- `correction_ladder_differences.csv/.pkl`；
- `path_feedback_decomposition.csv/.pkl`；
- `fee_rule_coverage.csv/.pkl`；
- `limit_rule_coverage.csv/.pkl`；
- `margin_rule_coverage.csv/.pkl`；
- `execution_policy_comparison.csv/.pkl`；
- `drawdown_episodes.csv/.pkl`；
- `drawdown_conditional_correlations.csv/.pkl`；
- `rolling_correlations.csv/.pkl`；
- `bootstrap_sampling_detail.csv/.pkl`；
- `bootstrap_paired_differences.csv/.pkl`；
- `bootstrap_rank_stability.csv/.pkl`；
- `multiple_testing_adjustment.csv/.pkl`；
- `multiple_testing_detectability.csv/.pkl`；
- `slippage_reality_diagnostic.csv/.pkl`；
- `annualization_diagnostic.csv/.pkl`；
- `walkforward_training_scores.csv/.pkl`；
- `walkforward_selected_strategy.csv/.pkl`；
- `robustness_exclusions.csv/.pkl`；
- `profit_concentration.csv/.pkl`；
- `test_inventory.csv/.pkl`；
- `file_traceability.csv/.pkl`。

Bootstrap 抽样明细使用规范化长表：`replication_id,block_id,block_start_index,block_start_date,requested_block_length,taken_length,target_start_position`；另存一行一个 `replication_id,target_position,sampled_date` 的映射，禁止把整组日期塞进单个 CSV 单元格。

`margin_rule_coverage` 至少包含组合总计、商品合计、T 合计和每个 `instrument×year` 的官方/推导覆盖率，并另列每个已知临时提保、节假日和交割特殊生效日的实际敞口及来源状态；不得只给一个全样本平均数。

`multiple_testing_adjustment` 必须把检验对象写为 `paired_mean_daily_net_return`；Sharpe 配对差另存描述性 Bootstrap 表，并带 `multiplicity_adjusted=false`。事件表同时保存运行内唯一的 `run_event_id` 和排除运行身份后可跨复跑稳定比较的 `business_event_key`。

## 5. 指标命名和中文展示

机器字段保持稳定英文 snake_case，报告显示中文名称。映射至少包含：

| 机器字段 | 中文 |
|---|---|
| `cagr` | 年化收益率 |
| `annualized_volatility` | 年化波动率 |
| `sharpe` | 夏普比率 |
| `sortino` | Sortino 比率 |
| `max_drawdown` | 最大回撤 |
| `calmar` | Calmar 比率 |
| `longest_underwater_trading_days` | 最长回撤恢复交易日数 |
| `net_profit_cny` | 净利润（元） |
| `commission_cny` | 客户手续费（元） |
| `slippage_cny` | 滑点成本（元） |
| `margin_utilization` | 保证金占用率 |
| `nominal_leverage` | 名义杠杆 |

比例在报告中统一转为百分数并明确小数位；底层保存全精度十进制。人民币报告保留 2 位，勾稽使用全精度。

### 5.1 绩效公式锁定

- 日净收益：账户仍有正权益时为 `equity_t/equity_(t-1)-1`；无持仓但账户有效的交易日为 0；
- 权益耗尽例外：若 `actual_equity<=0`，该场景为 `FAILED_GATE` 并在触发点停止；触发后不生成日收益，所有全区间绩效指标、22 策略排名、Bootstrap 和推荐结论均不得计算。只能报告触发日、触发前实际权益/负债、未平仓和部分账本勾稽；禁止合成有限责任收益曲线；
- CAGR（主口径）：`(equity_end/equity_start)^(365.2425/calendar_days)-1`；
- 算术年化收益（辅助）：日收益均值×252；
- 年化波动：日收益样本标准差（ddof=1）×sqrt(252)；
- Sharpe：无风险利率固定 0，日收益均值/样本标准差×sqrt(252)；
- Sortino：日收益均值/`min(return,0)` 的均方根×sqrt(252)，零下行波动时报 NA；
- 最大回撤：日权益相对截至当日历史峰值的最小值；
- Calmar：主口径 CAGR/abs(最大回撤)；零回撤时报 NA；
- 恢复期：从峰值后的首个回撤交易日到权益重新达到或超过原峰值的交易日数；未恢复事件标 `unrecovered=true`，不伪造结束日；
- 2026 及任何不完整年度均带 `is_partial_year=true`；
- 删除 2020/2024 只是在已实现日收益序列中删除对应日期后重新复合的切片诊断，不重跑仓位，不能称动态反事实；该表的“年化几何收益”固定为 `product(1+r)^(252/n_observations)-1`，不冒充连续日历 CAGR。

主报告同时给 CAGR（日历口径）和算术 252 日年化收益，避免把两种年化定义混称。

## 6. 强制中文报告

### `BACKTEST_ENGINE_AUDIT_v6.md`

- v6 架构和旧版迁移；
- G0—G8 逐项证据；
- 手续费、限价、保证金和未来函数审计；
- 账户与独立复算；
- 测试结果和覆盖率；
- 缺失、代理、异常、失败尝试；
- 修改文件清单和哈希。

### `BACKTEST_RESULT_REPORT_v6.md`

- v6 正式基准；
- 修复阶梯及直接/动态反馈；
- v3 与固定袖套对比；
- 年度、板块、品种、多空和成本；
- 回撤期相关性；
- 锁板政策敏感性；
- 保证金、杠杆、buffer 和拒单；
- 显性成本结构、B07/B08 冻结路径基础滑点 ±1 tick、分钟价格路径范围及其不能代表盘口的限制；
- 22 策略联合统计和真实滚动选择；
- Westfall–Young 有效区块数和可检测收益差、252 主年化与实际共同交易日年化诊断；
- 支持/反对替换 v3 的证据；
- 可靠性限制和不能据此得出的结论。

### `DATA_QUALITY_REPORT_v6.md`

- 行情、日历、合约、主力和 Panama；
- 手续费、保证金、限价规则覆盖；
- 跨源抽验和关键日人工核验；
- 代理规则占比；
- 五所 10 合约限价权限探针、RB/SC/M/TA/T 共 75 个 session-open 核验和早期保证金品种年度覆盖；
- 因果限价包住全历史 high/low 的必要条件检查，以及 12 个主力一价形态日和 RU2505 旧腿挑战集的来源核验；
- 数据快照哈希。

### `METHODOLOGY_AND_SELECTION_BIAS_REPORT_v6.md`

- 2022—2026 污染说明；
- 旧切片与真实滚动选择区别；
- 联合 Bootstrap、多重比较和排名稳定性；
- 未来 lockbox 的使用规则。

### `V6_HANDOFF_REPORT.md`

- canonical run；
- 完成/失败场景；
- 最终结论；
- 未关闭问题；
- 推荐人工复核顺序；
- 后续研究候选，但不自动执行。

若闸门失败，改为 `V6_BLOCKER_REPORT.md`，不得生成看似正式的结果报告。

## 7. 表格可追溯

报告中的每一张表和数字都带 `table_id`。`file_traceability` 记录：

```text
report_file, section, table_id, scenario_id,
source_file, filter_expression, aggregation_function,
code_version, data_snapshot_id
```

禁止从手工复制的终端输出生成正式表。报告中的参数表必须来自 `resolved_config` 和规则表，而不是模板常量。

## 8. 代理和异常展示

每个指标旁必须可获得：

- 代理手续费成交占比；
- 代理保证金敞口占比；
- 代理/推导限价订单占比；
- 缺失信号/数据天数；
- 拒单、部分成交和顺延次数；
- 受影响的品种、年份和金额。

代理不能被汇总后隐藏。若代理命中了决定性盈利年份或关键回撤日，要在执行摘要直接披露。

## 9. 版本和依赖可复现

manifest 至少记录：

- Python、pandas、numpy、pyarrow 等精确版本；
- 操作系统和时区；
- Git commit、dirty 文件列表；
- v6 源码和测试文件哈希；
- 配置、数据、日历和规则哈希；
- 随机种子；
- 启动命令、开始/结束时间、退出码；
- `attempt_count/effective_count/invalid_count/reused_count`。

另写 `economic_config_hash`：只哈希会影响经济结果的解析后配置、代码、数据和规则，明确排除 `run_id,scenario_id,output_path,started_at,attempt_id,replicate_of`。这些身份字段仍进入完整 manifest，因此两个确定性复跑的 manifest 哈希正常情况下不同。

依赖用锁文件精确固定；`pyproject` 的最低版本范围不足以单独证明复现。

## 10. canonical 晋升

机器运行仅当以下技术条件满足时标为 `COMPLETE_NONCANONICAL`：

- G0—G8 全部通过；
- 正式数据覆盖达标；
- 44 个计划有效运行全部完成，且跨所有时间戳目录的全局完整历史 `attempt_count`≤48；
- 全部注册场景状态清晰；
- CSV/pickle、报告和测试可追溯；
- 人工复核待办清单完整生成。

之后由项目所有者或其明确指定的复核人填写独立 `manual_review.json`，至少含 `reviewer_id,reviewed_at,manifest_sha256,checklist_status,notes`。签名前保持 `COMPLETE_NONCANONICAL`。签名通过后，晋升工具先写临时文件再原子替换项目级 `D:\FiveSectorMomentum\outputs\CANONICAL_V6.json`；该指针只含 `run_id,manifest_sha256,promoted_at,review_file_sha256`，不改运行底表。只有此时才标 `COMPLETE_CANONICAL`。

## 11. 不允许的报告措辞

禁止：

- “真实成交成本”——没有逐笔实盘回报时只能说模型/代理；
- “干净样本外 2022—2026”——该区间已被查看；
- “保证金修复必然提高收益”——动态反馈方向不确定；
- “锁板成交一定不可能”——日线无法观察排队；应描述保守假设和数据来源；
- “短周期无效/有效”——除非统计和市场阶段证据支持；
- “最佳策略”——应写预注册规则下的历史候选，并披露多重比较。
- “Sharpe 经 Westfall–Young 校正后显著”——本版正式多重检验的统计量是配对平均日净收益，不是 Sharpe；Sharpe 差仅为未经多重校正的描述性证据。
- “B08 是修正后的 v4.2 S1”或把 B08↔S1 终值差归给单一修复——B08 同时经过日历、费用、限价、保证金和末端流动性复检，只能按 A04→B02→B04→B06→B08 阶梯归因；
- “分钟 K 线验证了真实滑点/盘口成本”——分钟路径只能约束代理合理性，不能观察买卖价差、排队和真实冲击。
