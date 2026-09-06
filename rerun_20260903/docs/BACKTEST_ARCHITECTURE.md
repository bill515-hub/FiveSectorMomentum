# 中国期货五板块动量策略：回测框架架构与开发规范

> 文档状态：架构设计稿（MVP 基线，采用 pysystemtrade 风格价格点数口径）  
> 目标读者：策略研究、回测引擎和数据工程开发者  
> 默认频率：日频；收盘后生成信号，下一交易时段开盘成交

## 1. 结论与关键设计决策

本项目建议开发一个独立、轻量、可审计的 Python 回测框架，架构上吸收：

- `pysystemtrade` 的 Data / Config / System / Stage 分层和“信号—仓位—组合—账户”流水线；
- `backtrader` 的 Engine / DataFeed / Strategy / Broker / Analyzer 事件驱动模型。

但 **MVP 不把 pysystemtrade 或 backtrader 设为必需运行时依赖，也不需要把它们的源码下载进本项目目录**。原因是本策略最难的部分并不是通用指标计算，而是中国期货的连续合约、真实合约换月、按手取整、交易所手续费、保证金、涨跌停和夜盘交易日归属。直接套用任一框架，仍然需要较多定制。

建议做法：

1. 当前阶段仅参考两者的架构和术语；
2. 使用 `pyproject.toml` 管理本项目依赖，不复制第三方源码；
3. 如果后续需要做结果对照，再把 `backtrader` 作为可选开发依赖安装到虚拟环境；
4. `pysystemtrade` 更适合阅读和借鉴其系统化期货流程，不建议为了本 MVP 先引入整套依赖。

最重要的回测约束是：

> 巴拿马法复权价格只用于生成信号和估计“价格点数波动率”；订单、手续费、保证金和逐日盈亏必须落到当时可交易的真实期货合约上。信号链路不使用百分比收益。

## 2. 项目目标与非目标

### 2.1 MVP 目标

- 支持五个板块及可配置的品种池；
- 支持板块内横截面动量和单品种绝对动量；
- 支持波动率调整动量（即回溯期年化 Sharpe ，无风险收益参数为0）评分；
- 按 pysystemtrade 的 multiple prices / adjusted prices 思路构建巴拿马法连续价格；
- 动量、波动率、Sharpe 和手数计算使用绝对价格点差，而非百分比收益率；
- 以板块为风险预算单位，五个板块各占 20%；
- 支持真实期货合约换月、整数手数、合约乘数、保证金和交易费用；
- 严格避免未来函数，并保留每次运行的配置、数据版本和中间结果；
- 输出净值、持仓、订单、成交、换月、成本和绩效归因。

### 2.2 MVP 暂不包含

- 分钟级盘口撮合；
- 实盘交易接口；
- 参数自动寻优作为默认流程；
- 用机器学习预测主力合约或收益；
- 组合协方差最优化。MVP 先采用倒数波动率和固定板块风险权重，后续再加入相关性调整。

## 3. 策略的可执行定义

### 3.1 板块与初始品种池

品种池必须通过配置文件维护，不应写死在策略代码中。以下仅作为首版默认建议：

| 板块 | 方法 | 初始标的/候选池 | 板块风险权重 |
|---|---|---|---:|
| 黑色系 | 绝对动量 | `RB` 螺纹钢 | 20% |
| 农产品 | 横截面动量 | `A,C,CF,M,OI,P,RM,SR,Y` 等 | 20% |
| 化工能源 | 横截面动量 | `BU,EB,EG,FU,L,MA,PP,TA,V` 等 | 20% |
| 国债 | 绝对动量 | `T` 10 年期国债期货 | 20% |
| 基本金属 | 绝对动量 | `AL` 铝 | 20% |

注意：

- 品种是否纳入某板块是研究配置，不属于引擎逻辑；
- 同一品种不得同时出现在两个板块；
- 上市日期晚、历史不足、成交不活跃或临近退市的品种，在每个时点按当时可得信息过滤；
- 初版可先使用较稳定的小品种池，跑通后再扩充。

### 3.2 信号价格与价格变化

对每个品种至少建立三套相互关联的数据视图：

1. `multiple_prices`：当前交易合约、下一合约及其同日价格和合约代码；
2. `adjusted_price`：由 `multiple_prices` 通过巴拿马加减价差法生成的连续序列，用于动量和价格点数波动率；
3. `tradable_contract`：当日真实可交易合约，用于订单、成交、费用、保证金和盈亏。

默认用日结算价生成研究价格，也允许配置为收盘价。设巴拿马复权价格为 \(A_{i,t}\)，日价格变化为：

\[
d_{i,t}=A_{i,t}-A_{i,t-1}
\]

`d` 的单位是该期货品种的报价点数，不是百分比。策略的动量、波动率和风险标准化全部基于 `adjusted_price` 及其一阶差分。百分比收益只允许在账户净值绩效报告中使用，不进入交易信号或单手风险计算。

不得用供应商事后生成的“历史主力连续合约”直接回测，除非能证明其历史选约和拼接规则符合本项目的时点约束。供应商连续合约可以用于结果核对，但不是策略事实源。

### 3.3 动量评分

框架支持两类评分，策略运行时选择其中一种：

**波动率调整动量**

\[
M^{(L)}_{i,t}=A_{i,t}-A_{i,t-L}
\]

\[
score_{i,t}=\frac{M^{(L)}_{i,t}}{\hat{\sigma}^{P}_{i,t}\sqrt{L}}
\]

其中 \(L\) 是动量回溯交易日数，\(\hat{\sigma}^{P}_{i,t}\) 是只使用截至 \(t\) 日数据、从 \(d_{i,t}\) 估计的日价格点数波动率。除以波动率后，各品种分数才可用于横截面比较。

作为更贴近 Robert Carver 趋势规则的扩展，框架还应支持 EWMAC 点差：

\[
score^{EWMAC}_{i,t}=\frac{EWMA_{fast}(A_i)_t-EWMA_{slow}(A_i)_t}
{\hat{\sigma}^{P}_{i,t}}
\]

EWMAC 可作为后续可选信号；MVP 仍可先实现固定回溯期动量。

**回溯期年化 Sharpe**

\[
score_{i,t}=\frac{\operatorname{mean}(d_{i,t-L+1:t})}
{\operatorname{std}(d_{i,t-L+1:t})}\sqrt{252}
\]

虽然该比率最终无量纲，但分子和分母都来自绝对价格点差，没有先转换为百分比收益。

默认波动率估计采用与 pysystemtrade `robust_vol_calc` 相近的稳健指数波动率：对 `adjusted_price.diff()` 计算 EWMA 标准差，并施加绝对下限和滚动历史分位数下限。参考默认值为 EWMA 35 日、至少 10 个观测、500 日窗口的 5% 分位数下限，且禁止用未来波动率回填启动期。所有参数均通过配置覆盖。

为进一步贴近 pysystemtrade，原始分数之后预留 forecast scaling / capping：

\[
forecast_{i,t}=clip(raw\_score_{i,t}\times scalar_{i,t},-20,+20)
\]

`scalar` 的目标是使历史 forecast 的平均绝对值接近 10。它必须使用固定的事前参数，或只用截至 \(t-1\) 的扩展窗口估计；禁止在全样本上拟合后回填历史。MVP 中 forecast 只决定排序和方向，仓位大小仍由板块风险预算与价格点数波动率决定，不按 forecast 大小线性放大。后续若增加 Carver 风格连续仓位，可显式使用 `forecast / 10` 作为风险倍率。

### 3.4 横截面动量规则

农产品和化工能源分别独立选取，不跨板块排序。对每个调仓日：

1. 过滤不可交易、历史不足和流动性不足的品种；
2. 计算板块内各品种的 `forecast`（关闭 scaling 时等于 `raw_score`）；
3. 若最高分大于 `long_threshold`，做多最高分品种；
4. 若最低分小于 `short_threshold`，做空最低分品种；
5. 未满足方向阈值时，该方向为空仓。

因此一个横截面板块可能有 0、1 或 2 个持仓腿。默认阈值为 0。若多空两腿均激活，板块的 20% 风险预算在两腿之间各分 50%；若只有一腿激活，该腿使用整个板块风险预算；若没有激活，风险预算保留为现金，不转移给其他板块。

当最高分和最低分对应同一品种时，只允许产生一个方向，不能同时多空。MVP 要求至少两个合格品种才启用横截面选择。

为降低临界排名造成的频繁换手，后续可增加：持仓缓冲区、最短持有期、换仓分数差阈值；MVP 可先关闭，但接口需预留。

### 3.5 绝对动量规则

黑色系 `RB`、国债 `T`、基本金属 `AL` 分别独立判断；下列 `score` 指最终 `forecast`，关闭 scaling 时指 `raw_score`：

- `score > long_threshold`：目标方向为 `+1`；
- `score < short_threshold`：目标方向为 `-1`；
- 阈值区间内：目标方向为 `0`。

默认 `long_threshold = short_threshold = 0`。建议接口支持对称缓冲，例如从多头翻为空仓/空头时使用不同退出阈值，以控制零轴附近反复交易。

### 3.6 信号与成交时序

默认采用无未来函数的日频时序：

1. 交易日 \(t\) 开盘：执行 \(t-1\) 收盘后生成的订单；
2. 交易日 \(t\) 收盘/结算：更新持仓逐日盯市、连续序列和特征；
3. 使用截至 \(t\) 的数据生成新目标持仓；
4. 差分得到订单，排队到 \(t+1\) 的可交易时段执行。

中国期货夜盘属于下一交易日，数据规范化时应使用“交易日”而不是自然日作为主时间键。

## 4. 总体架构

采用“向量化研究 + 事件驱动交易”的混合架构：

```text
Raw Data Sources
      |
      v
Data Ingestion -> Validation -> Normalized Parquet + Metadata
      |                              |
      |                              v
      |                    Contract / Roll Registry
      |                              |
      v                              v
Multiple Prices -> Panama Adjusted Price -> Features -> Signals
                                                    |
                                                    v
                                            Sector Selection
                                                    |
                                                    v
                                          Risk & Position Sizing
                                            |
                                            v
                                     Target Positions
                                            |
                                            v
Event Engine -> Order Manager -> Futures Broker Simulator -> Ledger
                                                    |
                                                    v
                                      Analyzers / Reports / Artifacts
```

分工原则：

- 批量层负责可缓存、可复算的巴拿马连续序列、绝对价格点差、波动率和信号；
- 事件层负责有路径依赖的换月、下单、撮合、拒单、涨跌停、手续费、保证金和逐日盯市；
- 策略层只输出“目标风险/目标持仓”，不直接修改账户现金；
- Broker 只执行订单和维护账户，不重新解释策略信号。

## 5. 建议目录结构

```text
FiveSectorMomentum/
├─ pyproject.toml
├─ README.md
├─ configs/
│  ├─ strategy/
│  │  └─ five_sector_momentum.yaml
│  ├─ universe/
│  │  └─ cn_futures.yaml
│  └─ costs/
│     └─ cn_futures_costs.yaml
├─ data/                         # 默认不提交大文件到 Git
│  ├─ raw/
│  ├─ normalized/
│  ├─ features/
│  └─ manifests/
├─ docs/
│  └─ BACKTEST_ARCHITECTURE.md
├─ src/five_sector_momentum/
│  ├─ config/
│  │  ├─ models.py
│  │  └─ loader.py
│  ├─ domain/
│  │  ├─ enums.py
│  │  ├─ instruments.py
│  │  ├─ market.py
│  │  ├─ orders.py
│  │  └─ portfolio.py
│  ├─ data/
│  │  ├─ sources.py
│  │  ├─ schemas.py
│  │  ├─ validators.py
│  │  ├─ calendars.py
│  │  ├─ contracts.py
│  │  └─ continuous.py
│  ├─ features/
│  │  ├─ price_changes.py
│  │  ├─ volatility.py
│  │  └─ momentum.py
│  ├─ strategy/
│  │  ├─ base.py
│  │  ├─ cross_sectional.py
│  │  ├─ absolute.py
│  │  └─ five_sector.py
│  ├─ portfolio/
│  │  ├─ risk_budget.py
│  │  ├─ position_sizer.py
│  │  ├─ constraints.py
│  │  └─ rebalancer.py
│  ├─ execution/
│  │  ├─ broker.py
│  │  ├─ commission.py
│  │  ├─ slippage.py
│  │  ├─ margin.py
│  │  └─ roll.py
│  ├─ engine/
│  │  ├─ events.py
│  │  ├─ clock.py
│  │  └─ backtest.py
│  ├─ accounting/
│  │  ├─ ledger.py
│  │  └─ pnl.py
│  ├─ analysis/
│  │  ├─ metrics.py
│  │  ├─ attribution.py
│  │  └─ report.py
│  └─ cli.py
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ regression/
│  └─ fixtures/
└─ outputs/                      # 每次回测一个不可变 run 目录
```

## 6. 核心领域模型与接口

建议优先定义稳定接口，再填充实现。下面是概念签名，不要求逐字照搬：

```python
class MarketDataSource(Protocol):
    def bars(self, start, end, contracts) -> DataFrame: ...
    def contract_specs(self, as_of) -> DataFrame: ...
    def trading_calendar(self, exchange, start, end) -> Sequence[date]: ...

class ContinuousSeriesBuilder(Protocol):
    def build(self, instrument, bars, roll_rule) -> ContinuousSeries: ...

class FeatureStage(Protocol):
    def compute(self, as_of, market_view, config) -> DataFrame: ...

class Strategy(Protocol):
    def targets(self, as_of, features, state) -> list[RiskTarget]: ...

class PositionSizer(Protocol):
    def size(self, targets, portfolio, market, constraints) -> list[PositionTarget]: ...

class Broker(Protocol):
    def submit(self, orders: list[Order]) -> None: ...
    def on_market(self, event: MarketEvent) -> list[Fill]: ...

class Analyzer(Protocol):
    def on_event(self, event, portfolio) -> None: ...
    def finalize(self) -> dict: ...
```

### 6.1 必备实体

- `Instrument`：品种级标识，如 `RB`、`T`、`AL`；
- `Contract`：具体合约，如 `RB2701`，包含交易所、到期月；
- `ContractSpec`：乘数、最小跳动、保证金率、费用规则及生效区间；
- `Bar`：`trading_day/open/high/low/close/settlement/volume/open_interest`；
- `RollDecision`：旧合约、新合约、决定日、生效日、理由；
- `Signal`：评分、方向、所用数据截止时间和参数；
- `RiskTarget`：板块预算、品种预算、方向；
- `PositionTarget`：具体合约的目标整数手数；
- `Order/Fill`：订单与成交，保留拒绝/部分成交原因；
- `PortfolioSnapshot`：现金、权益、保证金、持仓、风险暴露；
- `LedgerEntry`：逐日盈亏、费用、滑点、保证金和现金变动。

所有关键表都应包含 `as_of` 或等价字段，以便审计“当时到底知道什么”。

## 7. 数据层设计

### 7.1 数据源接口与 Tushare

首个行情适配器使用 Tushare Pro，但领域层只依赖 `MarketDataSource` 接口，不能在策略或信号代码中直接调用 Tushare SDK。适配器负责调用、分页、重试、限频、字段映射、原始响应落盘和幂等更新。

首版使用的 Tushare 接口：

- `fut_basic`：普通期货合约列表、上市/退市日期和部分合约规格；
- `fut_daily`：真实合约日线 OHLC、结算价、成交量和持仓量；
- `fut_trade_cal`：各期货交易所交易日历；
- `fut_settle`：可获得时，用于补充按日手续费和保证金参数；
- `ft_limit`：可获得时，用于补充盘前涨跌停价和最低保证金率；
- `fut_mapping`：只作为供应商主力映射的对照数据，不直接替代本项目的 roll calendar；
- 历史手续费、保证金率、最小跳动和每点价值仍需与交易所规则或第二数据源交叉核验，不能仅因 Tushare 存在对应字段就视为完整事实源。

数据下载顺序应遵循 pysystemtrade 风格的数据管线：

```text
Tushare 原始合约与日线
  -> 标准化逐合约价格
  -> roll parameters / roll calendar
  -> multiple prices（PRICE / FORWARD / contract ids）
  -> Panama adjusted price
  -> sim data interface
```

密钥规则：

- token 仅从环境变量 `TUSHARE_TOKEN` 读取；
- 本地可使用不提交 Git 的 `.env`，仓库只允许提供值为空的 `.env.example`；
- token 不得出现在 YAML、源码、Notebook、测试夹具、日志、异常文本、输出 manifest 或文档中；
- 任何日志只显示掩码，例如 `****abcd`；
- 缺少 token 时明确报错，不允许回退到硬编码值。

本项目文档不会保存用户提供的 token。由于 token 已经通过对话明文传输，建议在 Tushare 控制台轮换后，再把新 token 仅写入本机环境变量。

### 7.2 标准化行情表

推荐内部存储使用 Parquet，最小字段为：

```text
trading_day, exchange, instrument, contract,
open, high, low, close, settlement, prev_settlement,
volume, open_interest, upper_limit, lower_limit,
source, ingested_at
```

约束：

- `(trading_day, contract)` 唯一；
- 价格非负，`high >= max(open, close)`，`low <= min(open, close)`；
- 缺失值、零成交、停牌和无结算价必须显式标记，不能静默前向填充；
- 原始数据不可覆盖，清洗后的数据带版本和校验摘要；
- 交易日历按交易所维护，并处理夜盘归属、节假日和临时休市。

### 7.3 合约元数据

元数据至少包括：

```text
contract, instrument, exchange, list_date, last_trade_date,
delivery_month, multiplier, tick_size,
initial_margin_rate, maintenance_margin_rate,
commission_open, commission_close, commission_close_today,
commission_mode, effective_from, effective_to
```

费用和保证金可能随时间变化，因此必须使用带生效区间的时间版本，不能用今天的规则覆盖全部历史。

### 7.4 Roll calendar 与 multiple prices

MVP 建议提供两种可配置的候选合约选择规则：

- `open_interest`：候选合约中持仓量最大；
- `volume_open_interest`：成交量与持仓量综合评分。

为避免未来函数：

- 用 \(t\) 日收盘后可得的数据作出决定；
- 最早在 \(t+1\) 生效；
- 增加最小剩余到期天数，禁止进入交割月附近；
- 增加滞后/确认天数或切换阈值，防止主力在两个合约间来回跳；
- 一般只允许向更远月滚动，异常回滚必须留下原因。

选约结果形成独立 `roll_calendar`，再与逐合约同日价格对齐，生成类似 pysystemtrade 的 `multiple_prices`：

```text
trading_day,
PRICE, PRICE_CONTRACT,
FORWARD, FORWARD_CONTRACT,
CARRY, CARRY_CONTRACT             # MVP 可选，为未来 carry 信号预留
```

即使 MVP 暂不交易 carry，也建议保留 `FORWARD` 及合约代码，因为巴拿马拼接需要旧合约和下一合约在同一天都有有效价格。

### 7.5 巴拿马法连续复权

本项目固定默认使用加减价差的 Panama back-adjustment，不再把比例复权作为默认选项。

当 `PRICE_CONTRACT` 从旧合约切换到新合约时，使用切换前一条 `multiple_prices` 记录计算：

\[
g_r=FORWARD_{r-1}-PRICE_{r-1}
\]

将 \(g_r\) 加到此前已有的全部 adjusted prices，然后追加新交易合约的当日 `PRICE`。也就是说，最新一段价格保持真实水平，历史段随每次换月平移；只改变价格水平，不改变旧段内部的绝对日点差。

若换月前一日旧、新合约不能同时取得有效价格，则该次拼接失败并进入数据异常队列，不允许用前向填充静默制造换月价差。实现可提供显式 `forward_fill` 调试开关，但生产回测默认关闭。

巴拿马复权可能使很早的历史价格变成零或负数。这不影响价格点差、EWMAC 和点数波动率，却再次说明不能在该序列上计算百分比收益。

连续数据至少输出：

- `adjusted_price` 和 `adjusted_price.diff()`；
- `multiple_prices`；
- 每日映射的真实合约；
- 换月缺口；
- 换月决定日和生效日。

绝不能在连续价格上直接计算账户盈亏，因为复权价格不可成交。

## 8. 回测流水线

借鉴 stage-based 系统，将一次运行拆为可缓存阶段：

1. `DataStage`：加载并验证行情、合约和元数据；
2. `RollStage`：按当时信息生成每日可交易合约映射；
3. `MultiplePricesStage`：对齐当前、下一和可选 carry 合约的同日价格；
4. `AdjustedPriceStage`：用巴拿马法生成 adjusted price 和绝对价格点差；
5. `FeatureStage`：以价格点数计算动量、Sharpe、稳健波动率和流动性；
6. `ForecastStage`：生成 raw score，并按配置进行滞后 forecast scaling 与 ±20 截断；
7. `SelectionStage`：完成板块内横截面选择和绝对动量方向判断；
8. `RiskStage`：分配 20% 板块风险预算并计算目标手数；
9. `RebalanceStage`：目标持仓减当前持仓得到订单；
10. `ExecutionStage`：在事件引擎内模拟成交、拒单、换月和成本；
11. `AccountingStage`：逐日盯市和账户记账；
12. `AnalysisStage`：指标、归因、图表和运行清单。

每个阶段应是确定性的：相同数据版本、代码版本、配置和随机种子必须得到相同输出。

## 9. 风险预算与目标手数

设当前权益为 \(V_t\)，组合年化目标波动率为 \(\sigma^*\)，板块风险权重为 \(b_s=20\%\)。板块的年化货币风险预算：

\[
B_{s,t}=V_t\sigma^*b_s
\]

若板块当前有 \(n_s\) 个激活持仓腿，则每腿预算：

\[
B_{i,t}=\frac{B_{s,t}}{n_s}
\]

设由巴拿马复权价格一阶差分得到的日价格点数波动率为 \(\hat{\sigma}^{P,daily}_{i,t}\)，则年化价格点数波动率为：

\[
\hat{\sigma}^{P,ann}_{i,t}=\hat{\sigma}^{P,daily}_{i,t}\sqrt{252}
\]

设每个报价点每手对应的人民币价值为 \(PointValue_i\)（通常来自合约乘数或经报价单位换算后的乘数），合约 \(i\) 的单手年化货币风险近似为：

\[
CR_{i,t}=PointValue_i\times \hat{\sigma}^{P,ann}_{i,t}
\]

未取整目标手数为：

\[
q^*_{i,t}=direction_{i,t}\times\frac{B_{i,t}}{CR_{i,t}}
\]

实际手数按配置进行向零取整或风险最接近取整。MVP 默认向零取整，避免系统性超预算。

这里不再乘当前期货价格，因为 \(\hat{\sigma}^{P}\) 已经是绝对价格点数的波动率。当前真实合约价格仍用于名义敞口、保证金和成交金额计算。国债等报价单位特殊的合约必须通过元数据测试确认 `PointValue`，不能假设 Tushare 的某个单一字段对所有品种都具有相同语义。

pysystemtrade 的仓位缩放文档以“当前真实合约价格作分母的百分比波动率 × 1% 价格变动的 block value”表述；在价格、点值和年化口径一致时，它应与本项目直接使用“价格点数波动率 × `PointValue`”代数等价。本项目选择后者以保持单位清晰，并把两种写法的等价性列为单元测试。

中国期货 MVP 均以人民币计价，`fx_rate_to_base=1`；仓位接口仍保留该字段，避免未来扩展外盘时重写风险模型。

必须再经过以下组合约束：

- 单品种最大手数和最大名义敞口；
- 组合最大保证金占用率；
- 组合最大名义杠杆；
- 波动率下限/上限及异常价格保护；
- 流动性参与率限制；
- 可用资金不足时按风险贡献等比例缩减，而不是按订单先后顺序抢资金。

说明：固定 20% 是“独立风险预算权重”，不等于资金各投入 20%，也不保证组合最终波动率恰好等于 \(\sigma^*\)。首版忽略相关性，后续可以在不改变策略接口的前提下增加协方差缩放。

## 10. 事件引擎与成交模型

### 10.1 事件类型

```text
SessionOpenEvent
MarketEvent
PendingOrderEvent
FillEvent / RejectEvent
SettlementEvent
SignalEvent
TargetPositionEvent
RollEvent
SessionCloseEvent
```

### 10.2 日频默认成交

- 信号日次日开盘成交；
- 市价单成交价默认为 `next_open + direction * slippage`；
- 滑点至少支持固定 tick、成交额基点和成交量参与率模型；
- 开盘即封涨停时买单/平空单不可成交，封跌停时卖单/平多单不可成交；
- 缺少次日开盘价或零成交量时订单延后或取消，并记录原因；
- 不允许成交价格越过当日涨跌停价；
- 大订单可按最大参与率形成部分成交。

### 10.3 费用

手续费模型至少支持：

- 按手固定费用；
- 按成交额比例；
- 开仓、平仓、平今不同费率；
- 换月产生“平旧 + 开新”两边费用和滑点。

### 10.4 逐日盯市与保证金

- 期货盈亏按真实合约和结算价逐日计算；
- 保证金占用按合约规则和当日结算价更新；
- 默认不模拟利息，后续可加入现金利息和保证金资金成本；
- 保证金不足时，先产生 `MarginCallEvent`；若启用自动减仓，按预定义规则执行并完整记录，不能隐式修改持仓。

## 11. 换月处理

换月应作为独立的交易原因，而不是信号方向改变：

1. `RollStage` 在 \(t\) 日决定 \(t+1\) 从旧合约切到新合约；
2. 策略的品种级风险方向保持不变；
3. `RollManager` 生成平旧合约和开新合约订单；
4. 两边分别经过可交易性、滑点、手续费和保证金检查；
5. 若旧合约能平、新合约不能开，账户可以短暂失去该品种敞口，不能假装完成无摩擦换月；
6. 报告中将信号换仓成本与合约换月成本分开。

## 12. 配置驱动示例

```yaml
data:
  source: tushare
  token_env: TUSHARE_TOKEN            # 这里只写环境变量名，绝不写 token
  raw_store: data/raw/tushare
  normalized_store: data/normalized

run:
  base_currency: CNY
  start: 2012-01-01
  end: 2026-08-31
  initial_capital: 10_000_000
  signal_time: settlement
  execution: next_open
  random_seed: 42

portfolio:
  annual_vol_target: 0.12
  max_margin_utilization: 0.50
  max_gross_notional_leverage: 4.0
  sector_risk_weights:
    ferrous: 0.20
    agriculture: 0.20
    chemical_energy: 0.20
    government_bond: 0.20
    base_metal: 0.20

signal:
  price_basis: settlement
  return_basis: absolute_price_diff   # 禁止改为 percent_return
  method: vol_adjusted_price_momentum # 或 price_diff_sharpe / ewmac
  lookback_days: 252
  vol_estimator: robust_ewma_price_diff
  vol_ewma_span_days: 35
  vol_min_periods: 10
  vol_abs_min: 1.0e-10
  vol_floor_enabled: true
  vol_floor_quantile: 0.05
  vol_floor_lookback_days: 500
  vol_floor_min_periods: 100
  backfill_initial_vol: false
  annualization_days: 252
  long_threshold: 0.0
  short_threshold: 0.0

forecast:
  scaling_enabled: true
  target_average_abs_forecast: 10.0
  cap: 20.0
  scalar_estimation: expanding_pooled
  scalar_min_periods: 500
  scalar_lag_days: 1
  use_forecast_magnitude_for_sizing: false

sectors:
  ferrous:
    mode: absolute
    instruments: [RB]
  agriculture:
    mode: cross_sectional
    instruments: [A, C, CF, M, OI, P, RM, SR, Y]
    min_eligible_instruments: 2
  chemical_energy:
    mode: cross_sectional
    instruments: [BU, EB, EG, FU, L, MA, PP, TA, V]
    min_eligible_instruments: 2
  government_bond:
    mode: absolute
    instruments: [T]
  base_metal:
    mode: absolute
    instruments: [AL]

eligibility:
  min_history_days: 300
  min_days_to_expiry: 20
  min_median_volume_20d: 1000
  min_median_open_interest_20d: 3000

roll:
  rule: open_interest
  stitch_method: panama
  panama_forward_fill: false
  decision_lag_days: 1
  confirmation_days: 2
  switch_ratio: 1.10
  forbid_backward_roll: true

execution:
  slippage_model: ticks
  slippage_ticks: 1
  max_volume_participation: 0.05
  allow_partial_fills: true
```

配置加载时应做跨字段校验，例如板块权重之和等于 1、阈值关系合法、日期范围足够覆盖预热期、品种不重复。

## 13. 账户、归因与报告

每次回测至少输出：

```text
outputs/{run_id}/
├─ manifest.json
├─ resolved_config.yaml
├─ data_manifest.json
├─ signals.parquet
├─ selections.parquet
├─ target_positions.parquet
├─ orders.parquet
├─ fills.parquet
├─ positions.parquet
├─ daily_equity.parquet
├─ roll_log.parquet
├─ costs.parquet
├─ metrics.json
└─ report.html
```

`manifest.json` 至少记录：Git commit、Python 版本、依赖锁摘要、配置摘要、数据摘要、运行时间、随机种子和框架版本。

报告至少包含：

- 年化收益、年化波动、Sharpe、Sortino、Calmar、最大回撤；
- 月度/年度收益、回撤持续期、尾部损失；
- 换手率、手续费、滑点、换月成本；
- 按板块、品种、多空方向的 P&L 和风险贡献；
- 保证金利用率、名义杠杆、未成交/拒单统计；
- 实际风险与目标风险偏离；
- 信号覆盖率及因数据不足而跳过的日期。

绩效计算必须使用扣除全部交易成本后的账户权益。研究报告同时展示毛收益和净收益，但禁止只汇报毛收益。

## 14. 防止常见回测偏差

### 14.1 未来函数

- 任何 `t` 日信号只允许读取 `timestamp <= t` 的数据；
- 主力合约选择和换月决定至少滞后一交易日生效；
- 滚动窗口必须先计算再显式 `shift` 到可用时点；
- 单元测试中对未来数据做扰动，历史信号必须不变。

### 14.2 幸存者偏差

- 品种池应带生效日期；
- 历史时点不得使用当时尚未上市品种；
- 退市品种不能从历史样本中静默删除。

### 14.3 连续合约伪收益

- 连续合约跳点不能计入账户 P&L；
- 账户 P&L 必须由真实合约的成交和结算价重建；
- 连续 adjusted price 点差与真实可交易 P&L 分开存储。

### 14.4 参数过拟合

- 首版先固定少量具有经济含义的参数；
- 优先做 walk-forward、子样本和参数稳定性分析；
- 参数选择区间和最终测试区间分离；
- 所有试验均保存配置和结果，不根据单次最好 Sharpe 选模型。

## 15. 测试策略

### 15.1 单元测试

- 绝对点差动量、点差 Sharpe、EWMAC 和稳健价格点数波动率的已知样例；
- 巴拿马拼接的换月价差方向、连续性、负历史价格和同段点差不变性；
- 点数波动率乘 `PointValue` 与百分比波动率/block-value 写法的单位和数值等价性；
- forecast scalar 只使用滞后数据，且最终 forecast 正确截断在 ±20；
- 横截面最高/最低选择、阈值和并列分数；
- 0、1、2 个激活腿时的板块预算分配；
- 合约乘数、整数手数和风险取整；
- 固定/比例/平今手续费；
- 涨跌停、零成交、部分成交和拒单；
- 主力切换滞后、禁止回滚和交割月过滤；
- 逐日盯市、保证金和换月 P&L。

### 15.2 集成测试

- 用 2 个品种、3 个合约、约 30 个交易日的手工数据跑完整链路；
- 手工逐日核对信号、订单、成交、费用、现金和权益；
- 确认连续价格产生跳点时账户不会获得虚假收益；
- 确认同一输入重复运行得到字节级或数值容差内一致的结果。

### 15.3 回归测试

保存一套小型“黄金数据集”和预期结果。任何引擎改动都比较：

- 每日权益；
- 目标与实际持仓；
- 总费用和换月次数；
- 关键绩效指标。

## 16. 开发阶段与验收标准

### Phase 0：数据契约

交付行情 schema、合约元数据 schema、日历和数据校验器。

验收：一份样例数据可被校验、版本化，并明确报告缺失和异常。

### Phase 1：研究流水线

交付 multiple prices、巴拿马 adjusted price、绝对价格点差波动率、两类动量评分及五板块选品。

验收：固定日期可追溯每个信号使用了哪些历史数据，未来数据扰动不改变过去信号。

### Phase 2：风险与仓位

交付板块 20% 风险预算、横截面腿内分配、整数手数和组合约束。

验收：构造样例中手算风险与框架结果一致，保证金不足时按比例缩减。

### Phase 3：事件回测

交付订单、成交、费用、涨跌停、部分成交、逐日盯市和换月。

验收：黄金数据集逐日账户结果一致，换月没有连续合约伪收益。

### Phase 4：报告与稳健性

交付绩效报告、板块归因、成本归因、walk-forward 和参数敏感性工具。

验收：一次命令生成完整、可复现的 run 目录和 HTML 报告。

## 17. 技术栈建议

核心依赖保持克制：

- Python 3.11 或 3.12；
- `tushare`：首个中国期货数据源适配器；
- `numpy`、`pandas`：计算与表格处理；
- `pyarrow`：Parquet；
- `pydantic`：配置和领域数据校验；
- `PyYAML`：配置；
- `pytest`、`hypothesis`：测试；
- `matplotlib`/`plotly`：报告图表；
- `typer`：命令行入口（可选）。

依赖应写入 `pyproject.toml` 并锁定版本。开发环境使用 `.venv`，不要把 `site-packages`、第三方仓库或下载压缩包提交到项目目录。

建议 CLI 最终形态：

```bash
fsm data validate --config configs/strategy/five_sector_momentum.yaml
fsm features build --config configs/strategy/five_sector_momentum.yaml
fsm backtest run --config configs/strategy/five_sector_momentum.yaml
fsm report build --run-id <run_id>
```

## 18. 已确认并进入实现的研究口径

1. 农产品和化工能源使用配置分类中当时已经上市、具有主力数据并完成预热的全部品种；首版配置共覆盖 53 个五板块品种，新增品种通过显式分类后自动纳入；
2. 信号价格使用收盘价；Panama 换月价差也使用同日收盘价；
3. 回溯期为单一 252 交易日，代表约 12 个月；
4. 评分为绝对价格点差的年化 Sharpe；
5. 每周最后一个交易日更新方向信号，波动率、权益和目标手数每日更新；持仓使用 10% no-trade buffer；
6. 优先采用 Tushare `fut_mapping` 并滞后一交易日生效；缺失时使用 OI 最大、110% 切换比、连续确认 2 日、离到期至少 20 日且禁止向近月回滚；
7. 同时测试 25%、27.5%、30% 年化目标波动率；保证金利用率上限 50%，交易所保证金率乘 1.25 的经纪商附加系数；
8. 优先采用 Tushare `fut_settle` 和 `ft_limit`；缺失时使用品种级保守保证金、每手与成交额费用的较高值，并测试 1 tick / 2 tick 滑点；
9. 对比 `retry` 与 `cancel_recalculate` 两种未成交处理；
10. 2015-01-01 至 2021-12-31 作为样本内，2022-01-01 至 2026-08-31 作为样本外，两个区间不重叠。

上述三档波动率、两种未成交模式和两档滑点组成 12 个预先定义场景。结果解释以样本外稳定性和场景敏感性为主，不按全样本最佳 Sharpe 反向选择参数。

## 19. 参考架构资料

- [pysystemtrade backtesting guide](https://github.com/pst-group/pysystemtrade/blob/develop/docs/backtesting.md)：Data、Config、System 和 Stage 的组织方式；
- [pysystemtrade futures data guide](https://github.com/pst-group/pysystemtrade/blob/develop/docs/data.md)：roll calendar、multiple prices 和 adjusted prices 数据流程；
- [pysystemtrade Panama implementation](https://github.com/pst-group/pysystemtrade/blob/develop/sysobjects/adjusted_prices.py)：`FORWARD - PRICE` 价差回加到历史段；
- [pysystemtrade robust price volatility](https://github.com/pst-group/pysystemtrade/blob/develop/sysquant/estimators/vol.py)：从 `price.diff()` 估计稳健价格点数波动率；
- [pysystemtrade EWMAC rule](https://github.com/pst-group/pysystemtrade/blob/develop/systems/provided/rules/ewmac.py)：均线点差除以非百分比价格波动率；
- [Tushare 期货合约信息](https://tushare.pro/document/2?doc_id=135)、[期货日线](https://tushare.pro/document/2?doc_id=138)、[主力映射](https://tushare.pro/document/2?doc_id=189)、[期货交易日历](https://tushare.pro/document/2?doc_id=467)、[结算参数](https://tushare.pro/document/2?doc_id=141) 和 [涨跌停价格](https://tushare.pro/document/2?doc_id=368)：首版数据适配器的数据契约；
- [Backtrader Cerebro](https://www.backtrader.com/docu/cerebro/)：引擎如何组织 DataFeed、Strategy、Broker、Analyzer；
- [Backtrader Data Feeds](https://www.backtrader.com/docu/datafeed/)：数据馈送抽象；
- [Backtrader Sizers](https://www.backtrader.com/docu/sizers/sizers/)：策略与仓位计算的职责分离。
