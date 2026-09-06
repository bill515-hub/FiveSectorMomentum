# T1 费率单位审计 + 独立影响重算

```
fee raw rows=36040, usable(source_status==tushare)=35873

特例(CFFEX rate字段=元/手): ['T']
  T: rate field distinct=[np.float64(3.0)], n=255

真费率型(rate>0 & fee缺/0 & 非CFFEX): ['RB', 'SP']
对照：RU 固定3元是否被正确排除: True

=== fee kind overview ===
instrument                 kind exchange  n_rows        distinct_trading_fee distinct_trading_fee_rate
        AL        fixed_per_lot     SHFE    1334                       [3.0]                     [0.0]
        AP        fixed_per_lot     CZCE    2035      [0.5, 5.0, 10.0, 20.0]                     [0.0]
         C        fixed_per_lot      DCE    3036                       [1.2]                     [0.0]
        CF        fixed_per_lot     CZCE    2981       [4.3, 6.0, 8.0, 10.0]                     [0.0]
        FG        fixed_per_lot     CZCE    2982 [2.0, 3.0, 6.0, 10.0, 15.0]                     [0.0]
        JD        fixed_per_lot      DCE    3036                  [1.5, 3.0]                     [0.0]
        LH        fixed_per_lot      DCE    1366                  [1.0, 2.0]                     [0.0]
         M        fixed_per_lot      DCE    2874                  [1.5, 2.0]                     [0.0]
        MA        fixed_per_lot     CZCE    2905   [1.0, 1.4, 2.0, 3.0, 6.0]                     [0.0]
         P        fixed_per_lot      DCE    3036                  [0.2, 2.5]                     [0.0]
        RB           rate_based     SHFE    1334                       [0.0]                [0.1, 0.3]
        RU        fixed_per_lot     SHFE    1334                       [3.0]                     [0.0]
        SC        fixed_per_lot      INE    1334                [20.0, 40.0]                     [0.0]
        SP           rate_based     SHFE    1334                       [0.0]              [0.02, 0.05]
        SR        fixed_per_lot     CZCE    2972                  [2.0, 3.0]                     [0.0]
         T CFFEX_rate_as_perlot    CFFEX     365                       [3.0]                [0.0, 3.0]
        UR        fixed_per_lot     CZCE    1615       [1.0, 2.0, 5.0, 10.0]                     [0.0]

=== rate-based instruments: 生效区间 ===
  RB: rate=0.1 从 2021-01-04 到 2026-08-31 (n=1330)
    /1000 => 0.000100 (=0.0100bp) ; /10000 => 0.000010 (=0.0010bp)
    官方对照: 万分之1（/1000 口径）vs 万分之0.1（/10000 口径）
  RB: rate=0.3 从 2023-09-05 到 2023-12-08 (n=4)
    /1000 => 0.000300 (=0.0300bp) ; /10000 => 0.000030 (=0.0030bp)
    官方对照: 万分之3（/1000 口径）vs 万分之0.3（/10000 口径）
  SP: rate=0.02 从 2026-08-31 到 2026-08-31 (n=1)
    /1000 => 0.000020 (=0.0020bp) ; /10000 => 0.000002 (=0.0002bp)
    官方对照: 万分之0.2（/1000 口径）vs 万分之0.02（/10000 口径）
  SP: rate=0.05 从 2021-01-04 到 2026-07-07 (n=1333)
    /1000 => 0.000050 (=0.0050bp) ; /10000 => 0.000005 (=0.0005bp)
    官方对照: 万分之0.5（/1000 口径）vs 万分之0.05（/10000 口径）

v3_formal_baseline [千分数/1000]: framework=1,272,705  recomputed=1,745,313  diff=+472,609

v3_formal_baseline [万分数/10000(框架现行)]: framework=1,272,705  recomputed=1,241,259  diff=-31,446
  /1000 口径逐笔差: mean=+102.65, p95=+329.96, 最大=+12311.79; 差异笔数(>0.01元)=1369/4604

v4_2_S1 [千分数/1000]: framework=3,998,744  recomputed=5,396,437  diff=+1,397,694

v4_2_S1 [万分数/10000(框架现行)]: framework=3,998,744  recomputed=3,856,445  diff=-142,298
  /1000 口径逐笔差: mean=+170.66, p95=+615.30, 最大=+36372.94; 差异笔数(>0.01元)=1619/8190

               run              口径  framework_commission  recomputed_commission    difference  abs_mean_per_fill_diff  max_abs_per_fill_diff
v3_formal_baseline        千分数/1000          1.272705e+06           1.745313e+06  4.726086e+05              131.133484             12311.7876
v3_formal_baseline 万分数/10000(框架现行)          1.272705e+06           1.241259e+06 -3.144612e+04               21.651580              5778.0000
           v4_2_S1        千分数/1000          3.998744e+06           5.396437e+06  1.397694e+06              222.905538             36372.9366
           v4_2_S1 万分数/10000(框架现行)          3.998744e+06           3.856445e+06 -1.422984e+05               34.872305              6444.0000
```
