# T6 价格换源（akshare 新浪 vs 仓库 fut_daily）

```
sina columns: ['date', 'open', 'high', 'low', 'close', 'volume', 'hold', 'settle']
RB2410: 采样20 匹配20 | maxdiff O/H/L/C = 0/0/0/8/3161
T2403: 采样20 匹配19 | maxdiff O/H/L/C = 0/0/0/0/103.8
SC2409: 采样20 匹配10 | maxdiff O/H/L/C = 0/0/0/0/0
AL2406: 采样20 匹配20 | maxdiff O/H/L/C = 0/0/0/40/0
MA409.ZCE: 仓库仅 0 行，跳过

summary: symbol  repo_rows  sampled  sina_matched  maxdiff_open  maxdiff_high  maxdiff_low  maxdiff_close  maxdiff_settle
RB2410        241       20            20           0.0           0.0          0.0            8.0        3161.000
 T2403        180       20            19           0.0           0.0          0.0            0.0         103.835
SC2409        629       20            10           0.0           0.0          0.0            0.0           0.000
AL2406        241       20            20           0.0           0.0          0.0           40.0           0.000
```
