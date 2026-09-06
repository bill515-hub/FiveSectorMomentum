# v6.1 下一次执行 Prompt v1.1 FINAL

将下面代码块中的内容作为下一次开发任务完整提交。

```text
请继续开发 D:\FiveSectorMomentum。本轮只执行 v6.1 PROVISIONAL_DAILY_ONLY，不运行 v6 A01、v6 的 44 场或其他研究。

开始前必须完整读取并严格执行：

D:\FiveSectorMomentum\docs\v6_1_daily_only_provisional_plan\V6_1_DAILY_ONLY_PROVISIONAL_EXECUTION_TASK_v1_1_FINAL.md

该文件是本轮唯一完整任务规范。原 `V6_1_DAILY_ONLY_PROVISIONAL_NEXT_STEP_PLAN.md` 已被取代，只保留为设计历史。机器参数必须在任何新增绩效结果产生前写入并冻结到 `V6_1_MACHINE_REGISTRY.yaml`。

还要只读核对：

- D:\FiveSectorMomentum\docs\v6_20260905_research_and_test_plan\V6_MACHINE_REGISTRY.yaml
- D:\FiveSectorMomentum\outputs\v6_20260906_135321_phase0_1a\PHASE0_1A_STATUS.json
- D:\FiveSectorMomentum\outputs\v6_20260906_135321_phase0_1a\V6_PHASE0_1A_READINESS_REPORT.md
- D:\FiveSectorMomentum\outputs\v6_20260906_135321_phase0_1a\V6_BLOCKER_REPORT.md
- D:\FiveSectorMomentum\outputs\v6_20260906_135321_phase0_1a\probe_errors.csv
- v3 与 v4.2 正式白名单输出和现有测试。

不得修改或覆盖任何 v2、v3、v4、v4.1、v4.2、v6 的源码、配置、缓存、审计、attempt 账本和回测输出。所有新增内容必须使用独立的：

- src/five_sector_momentum/v6_1/
- configs/five_sector_momentum_v6_1.yaml
- data/v6_1/
- tests/v6_1/
- outputs/v6_1_<唯一时间戳>/
- outputs/V6_1_GLOBAL_ATTEMPT_LEDGER.csv

第一阶段只修复和重跑数据探针，不得查看或生成 v6.1 绩效：

1. 修复旧探针把 Windows/网络 ConnectionError 中的 permissions 误判为 NO_PERMISSION 的缺陷；
2. 按 transport、HTTP、Tushare application response 和成功空表分层分类，至少区分 DATA、APPLICATION_NO_PERMISSION、RATE_LIMITED、NETWORK_BLOCKED、NETWORK_ERROR、ENDPOINT_ERROR、SILENT_EMPTY、KNOWN_NO_DATA_AFTER_POSITIVE_CONTROL 和 NOT_TESTABLE；
3. 网络类错误固定重试 3 次，等待 1、3、9 秒；保存安全消息码、异常类、错误层、WinError/HTTP 状态和不可逆指纹，不保存 token 或原始敏感请求；
4. 先运行基础连通性控制，再重跑 ft_limit、ft_mins 和 fut_settle；fut_settle 必须包含 RB2410.SHF、T2403.CFX 两个已知正控制以及 2015—2020 实际持仓暴露的 SHFE/INE 逐合约覆盖，历史行数只作锚点、不作硬编码验收值；
5. 0 个分钟观测必须记为 NOT_TESTABLE，不能报告成 0% 匹配；
6. 可尝试用 AkShare/新浪近期分钟数据对 RB、SC、M、TA、T 做最多各15日 session 约定诊断，但只能称近期部分验证，不能外推历史；
7. 输出独立 preflight 目录、CSV/pickle、证据报告和状态。

如果连通性控制仍被网络或沙箱阻断，输出 BLOCKED_PREFLIGHT_NETWORK_EVIDENCE 并停止，不得冻结注册表或运行完整历史。如果 ft_limit 意外已经可用且正式覆盖可行，输出 V6_CANONICAL_DATA_NOW_POSSIBLE.md 并停止，由我决定是否返回 v6 正式路径。

第二阶段在干净探针完成后、查看任何绩效前：

1. 创建并锁定 V6_1_MACHINE_REGISTRY.yaml、V6_1_EXPERIMENT_REGISTRY.md 和 resolved config；
2. 精确注册 14 个有效完整历史场景、2 个策略、16 次 attempt 上限；
3. 将 Phase A 测得的保证金供应商覆盖率、fallback 比例和证据哈希写入注册表；
4. P/S/C 共同参数逐字段继承 v6 v1.4；
5. R01/R02 用旧 `/10000` 费用语义，只作兼容复现；全部 P/S/C 使用修正 `/1000` 比例费率、T 固定费特例、×1.5 客户费率和开仓/平昨/平今分类；
6. 一价日代理只作用于引擎实际形成订单的真实合约和换月腿；12个主力一价形态日及 2025-04-07 RU2505 旧腿只作回归挑战集，不是真实涨跌停真值。

第三阶段解决兼容环境：优先使用能读取旧 pickle 的现有解释器，直接以 unittest 入口运行旧 v4.2 测试；不得修改旧 pickle 或旧测试。若需要 pytest，只允许安装到项目内 data/v6_1/runtime，不得升级全局 NumPy/Pandas。核心 pickle 或测试仍不兼容时输出 BLOCKED_BEFORE_R01 并停止。

之后严格按以下顺序执行，不得临时加场景：

R01/R02 → P01/P02 → P03/P04 → P05/P06 → P07/P08 → P09/P10 → P11/P12。

含义分别为：兼容锚；P0 有日线即成交的乐观代理；P1 方向性一价日拒单；P2 所有一价日双向拒单；P1 固定1 tick；P1 固定3 tick；P1 下一交易日收盘执行。

P11/P12 为保持执行时点单因素，非一价日以 daily close 为代理成交参考价，正常整数 tick 作为独立现金滑点只扣一次，不因 close±ticks 超出日内区间新增拒单；一价日仍使用 P1 规则，新仓从下一交易日开始计盈亏。

所有完整历史进程写入独立 v6.1 attempt 账本，最多16次。探针、测试、纯会计费用桥接和保证金影子诊断不计完整历史 attempt。任何闸门失败立即停止，不得继续消耗场景。

保证金基准使用滞后可得供应商逐日率，缺失时使用冻结的 v3 静态 fallback，客户乘数1.25；全部标记 VENDOR_DAILY_UNVERIFIED 或 STATIC_FALLBACK_PROXY。额外对 P03/P04 真实持仓和约束前目标做1.00/1.25/1.50三档影子利用率诊断，但不得反馈头寸、不得生成反事实收益曲线、不得临时增加完整历史场景。

必须新增并运行任务规范列出的单元测试、迷你市场手算、未来前缀、费用、换月、跨零、滑点唯一扣除、vendor-open/next-close P&L 边界、账户勾稽、确定性、secrets 和旧路径保护测试。

所有结果强制标记 PROVISIONAL_DAILY_ONLY。不得把 high==low 代理描述成真实锁板，不得把 vendor_daily_open 描述成已核验夜盘/日盘开盘，不得把保证金代理描述成官方历史保证金。

至少输出：preflight证据报告、V6_1_ENGINE_AUDIT.md、V6_1_BACKTEST_RESULT_REPORT.md、最终状态、14场景参数和指标、年度/板块/品种/多空贡献、成本、拒单、挑战集、保证金来源和影子诊断、账户勾稽、测试、attempt、修改文件和 manifest。所有底层表同时保存 CSV 和 pickle，并能从报告逐表追溯。

完成 v6.1 后停止，不进入 v6 A01、v5 或其他研究。最终汇报：干净探针结论、保证金真实覆盖、P0/P1/P2区间、机械拒单贡献、修正费用影响、1/3 tick敏感度、open/close差异、袖套是否改善年份集中/最大回撤/FG依赖、可靠性限制，以及是否值得购买数据权限返回 v6 正式路径。

本任务授权你在项目目录内新增 v6.1 代码、配置、测试、数据和输出；只读查询 Tushare、交易所网站和公开近期分钟数据；必要时仅在 data/v6_1/runtime 内安装测试或数据读取依赖。不得输出或复制 Tushare token，日志和 manifest 必须做 secrets 扫描。

完成检查后直接实施，不需要逐项等待确认。只有遇到会扩大范围、需要破坏性操作、网络权限无法解决或规范未定义的关键数据歧义时再询问。
```
