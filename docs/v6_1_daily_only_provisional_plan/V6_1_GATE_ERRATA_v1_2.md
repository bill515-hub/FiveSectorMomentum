# v6.1 G2闸门追加勘误（v1.2）

状态：**LOCKED_BEFORE_ANY_V6_1_PERFORMANCE**  
授权来源：用户在 `BLOCKED_BEFORE_R01` 后明确要求按推荐方式继续下一轮任务。

本勘误只修正测试闸门解释，不改变 `V6_1_MACHINE_REGISTRY.yaml` 中任何经济参数、场景、顺序、策略、数据代理或attempt上限。

## G2修订

1. `tests/test_v4_2_preflight.py` 是修复前历史诊断。它必须被原样运行，并稳定复现：第二项测试失败、历史不一致35条、方向变化3条。该精确失败签名记为 `EXPECTED_LEGACY_CAUSAL_DEFECT_REPRODUCED`；若意外通过或失败签名变化，反而阻断。
2. `tests/test_v4_2_repaired.py` 是P/S/C正式因果、日历、账户闸门，必须全部通过。
3. R01仅复现旧v3数值路径，标记 `LEGACY_COMPATIBILITY_ONLY_CAUSALLY_INVALID`，不能用于经济结论。
4. R02及所有P/S/C场景必须使用v4.2修复日历。任何修复路径的前缀不变测试失败仍立即停止。
5. 旧pickle必须可读；不得修改旧测试、旧pickle或历史输出。

上述变更解除上轮 `BLOCKED_BEFORE_R01`。其余v1.1 FINAL规范继续有效。
