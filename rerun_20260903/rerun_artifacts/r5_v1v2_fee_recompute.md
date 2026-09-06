# R5 — v1/v2 国债期货 T 每手手续费高估独立重算

> 结论先行：**v1/v2 的 T 腿每手手续费被框架按名义金额×2bp 的兜底公式收取，
> 实测约 183–219 元/手（基准约 205–207 元/手），而官方交易所费为 3.0 元/手、
> 框架自身 1.2× 客户口径为 3.6 元/手，高估约 57×。v1/v2 的成本、净利、夏普
> 不得用于任何成本数量级判断，仅可作方向参考。v1/v2 成本结论 VOID。**

---

## 1. 精确源码位置（框架如何算出 207 元/手）

### 1.1 `_commission` 方法（v1/v2 引擎共用）

文件：`src/five_sector_momentum/engine.py`

| 行号 | 代码 | 作用 |
|---|---:|---|
| 559 | `def _commission(self, bar, quantity, price, point_value) -> float:` | 方法入口 |
| 560 | `lots = abs(quantity)` | 取手数绝对值 |
| 561 | `fixed = self._value(bar, "trading_fee", 0.0) * lots` | 固定每手费（Tushare `trading_fee` 字段） |
| 562–563 | `reported_rate = self._value(bar, "trading_fee_rate", 0.0) / 10000.0` | 费率字段（注释称“万分数”） |
| 564 | `reported = fixed + lots * price * point_value * reported_rate` | 报告口径费用 |
| 565–568 | `fallback = max(lots * 5.0, lots * price * point_value * 0.0002)` | **兜底公式：每手 5 元 与 名义金额×2bp 取大** |
| 569 | `return max(reported * 1.2, fallback)` | 最终取“报告×1.2”与兜底的较大者 |

关键点：第 569 行把兜底当作**下限**，因此只要 `名义金额×2bp > 报告口径×1.2`，
实际计费就是兜底值，而不是官方费用。

### 1.2 兜底参数来源

| 文件 | 行号 | 值 |
|---|---:|---|
| `configs/five_sector_momentum.yaml`（v1） | 73 | `fallback_commission_per_lot: 5.0` |
| `configs/five_sector_momentum.yaml`（v1） | 74 | `fallback_commission_rate: 0.0002` |
| `configs/five_sector_momentum_v2.yaml`（v2） | 83 | `fallback_commission_per_lot: 5.0` |
| `configs/five_sector_momentum_v2.yaml`（v2） | 84 | `fallback_commission_rate: 0.0002` |

### 1.3 T 的点值（point_value）来源

文件：`src/five_sector_momentum/universe.py` 第 34 行

```
"RB": (10.0, 1.0, 0.13), "T": (10000.0, 0.005, 0.03), "AL": (5.0, 5.0, 0.13),
```

T 的 `point_value = 10000.0`（合约乘数 1 万元/点，名义 = 价格×10000）。
文件：`src/five_sector_momentum/engine.py` 第 621–624 行的 `_value` 在字段缺失/NaN
时返回传入的 fallback，因此 T 的 `point_value` 恒为 10000。

### 1.4 兜底如何变成“≈207 元/手”

```
T 每手兜底 = max(5.0, price × 10000 × 0.0002) = max(5.0, 2 × price)
```

观测到的 T 成交价区间为 **91.510 – 109.590**，故兜底 = **183.02 – 219.18 元/手**，
永远大于 5 元，也永远大于官方 3 元/手。基准场景加权平均实测 **205–207 元/手**。

---

## 2. 官方 T 手续费依据（用框架自己的数据验证）

### 2.1 框架 v3 费用表（`data/v3/fees/historical_fee_rules.pkl`）

独立读取后：T 品种 `open` 与 `close_non_today` 规则全部为
`fee_per_lot = 3.0`、`fee_rate = 0.0`；`close_today`（平今）为
`fee_per_lot = 0.0`（中金所现行标准平今免收，框架标注为 proxy）。

### 2.2 Tushare 原始结算参数（`data/v3/fees/tushare_fut_settle_daily_raw.pkl`）

独立读取后：T 共 365 行（2015-03-20 ~ 2026-08-31，exchange=CFFEX），
`trading_fee` 唯一值为 **3.0**；另有 255 行历史行把官方 3 元/手误存在
`trading_fee_rate` 字段（唯一值 **3.0**）——该 schema 漂移由
`src/five_sector_momentum/costs_v3.py` 第 50–60 行显式纠正为“官方 3 元/手”。

### 2.3 框架文档引用的官方来源

`src/five_sector_momentum/costs_v3.py` 第 14 行：

```
CFFEX_FEE_URL = "https://www.cffex.com.cn/cn/zjssf/20240701/39212.html"
```

`costs_v3.py` 第 50–60 行注释明确写有“CFFEX's official table proves … 3 yuan/lot”。

### 2.4 官方结论（精确）

| 口径 | 数值 |
|---|---:|
| 中金所 T 交易手续费（开仓 / 非日内平仓，每手单边） | **3.0 元/手** |
| 平今仓 | **0 元/手**（现行标准，框架 proxy 回填） |
| 框架 v1/v2 客户口径（`reported × 1.2`） | **3.6 元/手** |
| 框架 v1/v2 实际兜底（名义×2bp 下限） | **183.02 – 219.18 元/手**（随价格） |

---

## 3. 独立重算结果（从 fills.pkl 逐笔验证）

验证脚本：`rerun_20260903/rerun_artifacts/r5_recompute.py`（只读仓库、仅写 artifacts）。

对 v1/v2 全部成交的 T 行，逐笔复算
`fallback = max(5, price×10000×0.0002)`，并与 `fills.pkl` 中记录的 `commission` 比较：
**全部 T 成交的 `|记录值 − 兜底公式| / 手 = 0.000000`**，即框架记录的 T 手续费
**恰好等于兜底公式**，无一例外。

### 3.1 基准场景（两版报告均固定为 27.5% 目标、2 tick、cancel_recalculate）

| 项目 | v1（`outputs/20260901_180546`） | v2（`outputs/v2_20260901_213543`） |
|---|---:|---:|
| 基准场景目录 | `vol_0p275__cancel_recalculate__slip_2p0t` | `vol_0p275__cancel_recalculate__slip_2p0t` |
| T 成交手数 | 7,409 | 14,032 |
| 框架计收 T 手续费 | **1,517,410.06 元** | **2,905,927.85 元** |
| 框架实际每手 | **204.8063 元/手** | **207.0929 元/手** |
| 正确交易所费（3.0 元/手） | 22,227.00 元 | 42,096.00 元 |
| 正确客户费（3.6 元/手） | 26,672.40 元 | 50,515.20 元 |
| 相对客户费多计 | 1,490,737.66 元 | 2,855,412.65 元 |
| **高估倍数（vs 客户 3.6）** | **56.89×** | **57.53×** |
| 高估倍数（vs 交易所 3.0） | 68.27× | 69.03× |

> v2 基准 T 手续费 2,905,927.85 元 ≈ 290.6 万元，与审计口径一致；
> 正确客户费约 5.05 万元（若再按平今免收则更低），多计约 **285.5 万元**。

### 3.2 全 12 情景矩阵合计（v1/v2 各 12 个 vol×unfilled×slip 场景）

| 项目 | v1（12 情景合计） | v2（12 情景合计，不含 buffer_0pct 参考） |
|---|---:|---:|
| T 成交手数 | 94,744 | 193,566 |
| 框架计收 T 手续费 | 19,429,295.97 元 | 40,157,846.62 元 |
| 框架实际每手 | 205.0715 元/手 | 207.4633 元/手 |
| 正确客户费（3.6 元/手） | 341,078.40 元 | 696,837.60 元 |
| 相对客户费多计 | 19,088,217.57 元 | 39,461,009.02 元 |
| 高估倍数（vs 客户 3.6） | 56.96× | 57.63× |

（v2 若加 `buffer_0pct_reference`，T 手数 18,393、手续费 3,802,916.32 元、每手 206.7589 元，同样全为兜底值。）

---

## 4. 根因精确定位（比“fut_settle 为空”更准确）

审计与 v1/v2 报告把成因归于“`fut_settle` 返回空”。本独立重算确认：

1. `data/raw/tushare/fut_settle.pkl` 确为空 DataFrame（shape `(0, 0)`），
   故 v1/v2 bars 中 `trading_fee`/`trading_fee_rate` 均为 NaN，
   `_value(..., fallback=0.0)` 返回 0 → `reported = 0`。
2. **但即使 `fut_settle` 有数据**，对 T 而言 `reported × 1.2 = 3.6 元/手`，
   仍小于兜底 `2×price ≈ 183–219 元/手`。第 569 行的 `max(reported*1.2, fallback)`
   把兜底作为下限，因此 **T 仍会被收 207 元/手**。

因此根因是**兜底公式把“名义金额×2bp”设为固定每手费品种（T）的下限**，
而不是单纯的数据缺失。数据缺失只是让 `reported` 从 3.6 变成 0，不改变最终取值。

---

## 5. 结论声明（支持 M9）

- **v1/v2 的 T 腿手续费为系统性数量级高估**：实测每手 205–207 元 vs
  官方 3.0 元/手（框架客户口径 3.6 元/手），高估 **≈57×**（约 56.9×–57.6×）。
- v1 基准多计 **149.07 万元**，v2 基准多计 **285.54 万元**；
  12 情景矩阵合计 v1 多计 **1,908.82 万元**、v2 多计 **3,946.10 万元**。
- **方向是保守的**（费用高估 → 净利/夏普低估），但数量级错误使任何绝对成本、
  净利、夏普、回撤成本敏感度结论失真。
- **v1/v2 的成本与净利结论 VOID / 仅方向参考**；成本数量级结论一律以 v3+
  （Tushare 规则 × 客户倍数）为准。该声明对应 M9。

---

## 附：可复现脚本

- `rerun_20260903/rerun_artifacts/r5_inspect.py`（fills 结构探查）
- `rerun_20260903/rerun_artifacts/r5_recompute.py`（官方费率验证 + 逐笔兜底复算）

运行：`python D:\FiveSectorMomentum\rerun_20260903\rerun_artifacts\r5_recompute.py`
（Python 3.13.8 / pandas 2.2.3 / numpy 2.2.3）。
