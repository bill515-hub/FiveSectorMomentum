# v6 新增建议采纳与取舍记录

版本：v1.4 FINAL  
日期：2026-09-06  
状态：`LOCKED_BEFORE_RESULTS`；截至冻结未运行、未查看任何 v6 新回测结果。

## 1. 决策原则

两份建议总体支持 v6 的四层架构、44 个有效运行、48 次 attempt 上限和 G0—G8 闸门。本轮只吸收能减少歧义、提前暴露不可行性或增强审计性的内容；不因建议增加信号、权重、品种或完整历史场景，也不放宽失败纪律。

处理标签：

- `ADOPTED`：按建议落入规范；
- `ADOPTED_WITH_GUARDRAIL`：方向采纳，但加上因果/权限/统计限制；
- `ALREADY_COVERED_STRENGTHENED`：原方案已有，本轮机器化或加严；
- `NOT_ADOPTED`：会破坏预注册、证据不足或需要新授权。
- `REVISED_AFTER_AUDIT`：此前结果前修订引入了新经济行为，后续审计发现后在首个结果产生前撤回或收窄。

## 2. 建议一

| 建议 | 决策 | 落地位置 | 说明 |
|---|---|---|---|
| G0-DATA-FEASIBILITY 作为首个 go/no-go | `ALREADY_COVERED_STRENGTHENED` | `03` §1.1、`05` G0、`10` Phase 1 | 在 corrected 策略/账户代码前先做 10 合约限价权限、早期 margin 覆盖和 75 点 session-open 探针；失败不启动 A01 |
| 先升级 Tushare 或引入第二供应商 | `ADOPTED_WITH_GUARDRAIL` | `03` §1.1 | 可在 blocker 中建议；购买、升级或引入新源需要用户另行授权，不能由本计划自动执行 |
| runner-up 排序、tie-break、重新定规模写进配置 | `ADOPTED` | `04` §6、`V6_MACHINE_REGISTRY.yaml` | 多/空方向分别稳定排序；用 runner 自身点差波动率、乘数和原腿风险预算调用同一 sizing，不复制手数、不级联 |
| 12 个锁板日和 RU2505 直接作为拒单真值 | `ADOPTED_WITH_GUARDRAIL` | `03` §3.4、`05` G4、`07` §6 | 12 日来自 `high==low` 形态，不能自动升格为官方限价；作为固定挑战集，只有来源、价位和订单方向同时确认后才断言拒单 |
| B01—B08 坚持单因素并记录首个差异 | `ALREADY_COVERED_STRENGTHENED` | `06` §4、`07` §11、`10` Phase 3 | 保留 A04→B02→B04→B06→B08 和 A06→B01→B03→B05→B07；信号、目标、订单差异分层记录 |
| Westfall–Young 只检验平均净收益；22 策略唯一列举 | `ADOPTED` | `06` §12.2、`09` §4/§11、机器注册源 | Sharpe 差明确未经多重校正；22 个 strategy ID 与 provider scenario 只由 YAML 定义 |
| 防 set/hash 未定义顺序 | `ADOPTED` | `07` §14、机器注册源 I01/I02 | B07/B08 与 I01/I02 使用不同 `PYTHONHASHSEED`，业务结果仍须一致；排名和事件序号全部显式稳定排序 |
| 范围冻结 | `ALREADY_COVERED_STRENGTHENED` | `06` §15、`10` §15 | 新想法只进未来研究库，不能改 44 场或用验证结果调参 |

## 3. 建议二

| 建议 | 决策 | 落地位置 | 说明 |
|---|---|---|---|
| 限价、早期保证金、next_open 三项先测 | `ADOPTED` | `03` §1.1/§3.3/§3.4、`05` G0/G4、`10` Phase 1 | 三者均为 A01 前阻断项；不足时只出 blocker |
| 保证金不足时预注册全案 PROVISIONAL 或 v6a 退路 | `ADOPTED_WITH_GUARDRAIL` | `03` §1.1 | 本 v6 不自动换研究目标；先补官方推导，仍不足即停止。PROVISIONAL 全案或 v6a 需用户另行授权、另起注册 |
| 用全历史 OHLC 验证推导限价 | `ADOPTED_WITH_GUARDRAIL` | `03` §3.4、`05` G4、`07` §6 | `upper>=high/lower<=low` 是强必要条件但非充分证明；不能用当日 OHLC 反向生成开盘前限价 |
| 量化滑点代理现实性与 ±1 tick | `ADOPTED_WITH_GUARDRAIL` | `06` §12.7、`09` 输出/禁语 | 只在 B07/B08 冻结真实 fills 上做基础滑点 ±1 整数 tick，并用分钟路径作范围诊断；不增加动态场景、不声称真实盘口成本 |
| 基础设施失败返还 attempt | `NOT_ADOPTED` | `V6_MACHINE_REGISTRY.yaml`、`10` §11 | 返还会使 48 上限可被事后解释。任何已写 `STARTED` 的完整历史进程均计数；用探针、迷你市场和逐日勾稽保护 4 个储备槽 |
| 预告 Westfall–Young 低功效 | `ADOPTED` | `06` §12.8 | 输出区块数、HAC SE、step-down 临界值和可检测收益差；未拒绝不等于策略等价 |
| 同时报告实际共同交易日年化 | `ADOPTED_WITH_GUARDRAIL` | `06` §12.9、`09` 汇总表 | 252 仍是唯一主口径和选择口径；`D_obs` 年化只作诊断，不可择优切换 |
| 定义权益耗尽与强平 | `REVISED_AFTER_AUDIT` | `04` §7.3、`08` §9、`07` §8、机器注册源、`PLAN_REVIEW_ERRATA.md` E50—E52 | v1.3 的逐日强平会把 65%/78% 目标约束变成新经济行为并污染 B 组。v1.4 恢复旧语义：只做目标缩量和实际超限诊断；`equity<=0` 则保存部分账本并停止，不生成强平或合成有限责任曲线 |
| 单一机器可读 registry | `ADOPTED` | `V6_MACHINE_REGISTRY.yaml`、`00` 权威顺序、`05` G0 | YAML 是精确机器源；人类文档解释，resolved config 必须逐字段校验 |
| 表级哈希用规范序列化 | `ADOPTED` | `03` §2、`09` §3、`07` §2 | 采用 `canonical_json_rows_v1`；pickle 字节只作文件完整性，不作跨环境内容身份 |
| 逐日/事件级即时勾稽、迷你市场先跑 | `ADOPTED` | `10` Phase 1/3、`07` | 在消耗完整历史 attempt 前覆盖 B07/B08 关键状态；运行中尽早失败并保留事件 |
| 禁止把 B08 简称为修正后的 S1 | `ADOPTED` | `09` §11 | 只能沿单因素比较边归因，不能把五项累计变化归给一种修复 |

## 4. 没有改变的核心研究设计

- 仍是 44 个计划有效完整历史运行、48 次全局 attempt；
- 仍只有 v3、20skip5、250、固定 50:50 袖套作为核心对象；
- B07/B08 保留旧 pre-cap 并只增加 post-cap，保持单因素；
- 不增加频率、信号窗口、权重、品种或成本动态场景；
- 默认保留审计修正后的 v3，只有预注册门槛全部满足才可推荐袖套；
- 数据不可行、未来函数、账户不平或净额收费错误时仍立即停止。

## 5. 执行者应如何使用本记录

先读 `V6_MACHINE_REGISTRY.yaml` 取得精确常数和场景，再读 `06_EXPERIMENT_REGISTRY.md` 理解比较目的。本文件只解释建议为何被采纳或拒绝，不是第三套参数源；若本文件与机器注册源冲突，以机器注册源为准并触发 G0 文档一致性失败。
