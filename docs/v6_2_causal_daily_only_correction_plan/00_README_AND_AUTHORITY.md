# v6.2 因果日线纠偏研究：文档权威说明

本目录只定义下一轮任务，不运行回测、不修改既有 v6.1 结果。

执行时的权威顺序：

1. `V6_2_CAUSAL_DAILY_ONLY_CORRECTION_TASK_v1_0_FINAL.md`：唯一完整任务规范；
2. 下一轮在任何新增绩效产生前创建并冻结的 `V6_2_MACHINE_REGISTRY.yaml`：精确机器参数权威；
3. `V6_2_RECOMMENDED_EXECUTION_PROMPT.md`：推荐启动提示词，不得覆盖任务规范。

本计划继承 v6 v1.4 的经济参数和 v6.1 的数据证据等级，但不继承 v6.1 的执行日完整 `[low, high]` 成交筛选。

计划状态：`FINAL_BEFORE_V6_2_RESULTS`。  
计划版本：`1.0 FINAL`。  
研究标签：`v6_2_PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION`。

