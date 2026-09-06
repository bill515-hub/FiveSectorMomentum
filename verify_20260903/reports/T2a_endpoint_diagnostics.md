# T2a 端点诊断：tushare fut_settle / ft_limit 单合约 vs 批量

脚本：`verify_20260903/tmp/t2a_endpoint_diag.py`（token 从 ROOT/.env 读取，未在任何输出回显）
输出：`tmp/t2a_endpoint_diagnostics.csv`

## 实测结果（2026-09-03）

| 端点 | 案例 | 状态 | 行数 |
|---|---|---|---|
| fut_settle | 单合约 RB2410.SHF（20240501-20240930） | ok | **103** |
| fut_settle | 单合约 MA401.ZCE（20230901-20231231） | ok | 0（该端点 CZCE 部分合约/时段无数据） |
| fut_settle | 单合约 T2403.CFX（20231001-20240315） | ok | **9** |
| fut_settle | 批量 6 合约逗号列表（`data_source.py` 同形调用） | ok（无异常） | **0** |
| ft_limit | 单合约 RB2410.SHF | **ERROR：无该接口访问权限** | - |
| ft_limit | 单合约 MA401.ZCE | **ERROR：无该接口访问权限** | - |
| ft_limit | 批量 6 合约 | **ERROR：无该接口访问权限** | - |

## 结论

1. **H1（fut_settle 0 行）根因坐实**：`fut_settle` 端点本身可用（单合约 RB2410 返回 103 行；仓库费用脚本逐合约下载得到 36,040 行也证明这一点），但 `data_source.py:247-255` 采用 6 合约逗号列表批量调用——该端点**不支持多合约参数，静默返回空 DataFrame（不抛异常）**，因此每个批次都为空、拼接后 0 行、`warnings=[]`（告警只挂在"批次抛异常"分支上，空返回不触发）。
2. **ft_limit 不可用坐实**：当前 token 对 `ft_limit` 无访问权限（单合约即抛"没有接口访问权限"）。下载当日（2026-09-01）manifest 无告警、0 行，说明当时该端点同样未返回数据（权限缺失或空返回），且因 optional=True 被静默跳过。
3. 修复方向明确：fut_settle 改为逐合约下载（复用 `download_v3_fee_data.py` 模式即可，且数据已在 `data/v3/fees/` 事实上补齐）；ft_limit 需要更高权限 token 或改用交易所公告/结算参数推算停板价。
