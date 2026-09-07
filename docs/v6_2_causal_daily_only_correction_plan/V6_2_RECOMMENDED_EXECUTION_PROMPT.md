# v6.2 推荐执行 Prompt

```text
请继续开发 D:\FiveSectorMomentum。本轮只执行 v6.2 因果日线纠偏研究，不运行 v6 A01/44 场、v5 或其他策略研究。

开始前必须完整读取并严格执行：

D:\FiveSectorMomentum\docs\v6_2_causal_daily_only_correction_plan\00_README_AND_AUTHORITY.md
D:\FiveSectorMomentum\docs\v6_2_causal_daily_only_correction_plan\V6_2_CAUSAL_DAILY_ONLY_CORRECTION_TASK_v1_0_FINAL.md

其中任务文档是本轮唯一完整规范。还要完整读取：

- D:\FiveSectorMomentum\outputs\v6_1_postrun_audit_20260906_210510\V6_1_POST_RUN_INDEPENDENT_AUDIT.md
- D:\FiveSectorMomentum\outputs\v6_1_postrun_audit_20260906_210510\audit_findings.csv
- D:\FiveSectorMomentum\outputs\v6_1_20260906_155224\V6_1_ENGINE_AUDIT.md
- D:\FiveSectorMomentum\outputs\v6_1_20260906_155224\V6_1_BACKTEST_RESULT_REPORT.md
- D:\FiveSectorMomentum\outputs\v6_1_20260906_155224\V6_1_DETAILED_RESULT_ANALYSIS.md
- v6 v1.4、v6.1 的机器注册表、正式白名单输出和相关测试。

不得修改或覆盖任何 v2、v3、v4、v4.1、v4.2、v6、v6.1 源码、配置、缓存、审计、账本和输出。所有新增内容使用独立的 src/five_sector_momentum/v6_2/、configs/five_sector_momentum_v6_2.yaml、data/v6_2/、tests/v6_2/、outputs/v6_2_<唯一时间戳>/ 和 outputs/V6_2_GLOBAL_ATTEMPT_LEDGER.csv。

本轮的首要目标是移除 v6.1 vendor-open 路径中的执行层未来信息：订单在 d 日开盘成交时，不得使用 d 日完整 high、low、close、settlement、最终 volume 或最终 OI 决定是否成交或成交多少。主基准以 vendor_daily_open 为参考成交价，基础滑点、换月滑点和市场冲击作为独立现金成本只扣一次；不得再因 open±ticks 超出最终日内区间拒单或裁剪价格。成交容量只使用截至 t 日可得的滞后流动性统计。

high==low 只能作为事后 OHLC 形态诊断，不能进入正式开盘成交接受函数，不能描述成真实涨跌停。必须具体回放既有 12 个主力一价形态日和 2025-04-07 RU2505 旧换月腿，但继续标明它们不是官方限价真值。

先只读完成 Phase A：验证旧结果哈希，审计并规范化现有 fut_settle 缓存，确定保证金单位、重复键、覆盖和至少一交易日 lag 的 as-of 合并规则。随后在查看任何 v6.2 新绩效前，创建并冻结 V6_2_MACHINE_REGISTRY.yaml、V6_2_EXPERIMENT_REGISTRY.md、resolved config 和 freeze 记录。精确注册任务文档规定的 12 个场景、2 个策略、14 次 attempt 上限，不得临时增加场景或参数。

保证金必须按预注册单因素阶梯处理：R01/R02 复现 v6.1 P03/P04；B01/B02 只移除未来区间筛选、仍用静态 fallback；B03/B04 才启用至少滞后一交易日的供应商方向保证金，缺失或过期时用冻结静态 fallback。每个使用键必须记录 rate date、known time、单位转换、来源码和规则 ID。不得把供应商数据写成官方保证金。

严格按以下顺序运行：

R01/R02 → B01/B02 → B03/B04 → S01/S02 → S03/S04 → T01/T02。

R 为兼容闸门；B01/B02 为执行纠偏；B03/B04 为保证金接入后的正式 v6.2 日线代理；S01/S02 为固定 1 tick；S03/S04 为固定 3 tick；T01/T02 为下一交易日 close 执行压力。对同一订单、账户和滞后容量输入，滑点 tick 不得改变当次成交资格或手数；完整历史允许成本改变权益后自然产生路径反馈。open/close 场景除执行参考时点和新仓 P&L 生效边界外不得改变其他经济参数。

所有完整历史运行进入独立 attempt 账本，最多 14 次。任一复现、未来字段访问、保证金 lag、费用、滑点唯一扣除、账户勾稽、确定性、secrets 或旧路径保护闸门失败时立即停止并输出 blocker，不得继续消耗场景。

必须完成任务规范列出的单元测试、迷你市场手算、字段访问白名单、未来前缀、保证金 as-of、费用/反手/换月、滑点唯一扣除、open/close P&L 边界、袖套净额、账户勾稽和确定性测试。报告必须修正换手分母、成本分项 tick_size、next-close 双重展示、挑战集空占位及 AL 集中度分母问题。

全部结果继续标记 PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION，不得称为真实开盘成交、真实涨跌停、真实盘口、官方历史保证金或实盘可实现收益。

完成后输出任务规范要求的全部 CSV/pickle、V6_2_ENGINE_AUDIT.md、V6_2_BACKTEST_RESULT_REPORT.md、V6_2_V61_CORRECTION_BRIDGE.md、最终状态、manifest、测试和修改文件清单。完成 v6.2 后停止。

最终向我汇报：纠偏前后参照与袖套收益/回撤变化；袖套优势是否仍存在；差异化拒单曾放大多少优势；供应商保证金实际接入率及路径影响；固定 1/3 tick 和 open/close 的干净敏感性；年份、AL/FG、板块和多空集中；剩余可靠性限制；以及是否值得购买 ft_limit/分钟权限返回 v6 正式路径。

完成检查后直接实施，不需要逐项等待确认。只有遇到会扩大范围、需要破坏性操作、保证金单位无法合理确定或任务规范未定义的重要数据歧义时再询问。
```
