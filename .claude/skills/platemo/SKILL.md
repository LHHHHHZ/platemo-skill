---
name: platemo
description: "Run, compare, and assist one iteration of multi-objective optimization experiments on PlatEMO. Use for PlatEMO batch simulations, experiment metrics, reproducible comparisons, and algorithm iteration. 在 PlatEMO 上批量仿真、比较多目标优化实验并辅助迭代算法。"
license: MIT
---

用用户正在使用的语言回复，命令和日志保持英文。面向已安装的 PlatEMO 算法，不预设用户研究某个算法或问题族。基础环境是 MATLAB R2019a+ 和装有 NumPy、SciPy 的 Python，特殊依赖按适配器加载。

## 识别任务

- run：运行实验；compare：分析已有数据；iterate：用户明确要求时修改目标算法并评估一轮。
- 支持用户指定 algorithms、problems、M、D、N、maxFE、runs、metrics、baseline、seeds、config 和 quick/standard/full。
- 用户配置优先。未点名算法时询问，不默认指定某一算法。问题族不明确时先明确研究目标，按 [测试集与预算](references/benchmarks.md) 选择，不自动转为大规模问题。
- 用 classdef 确定类名，文件夹名可能不同；检查编码、目标数、约束支持及问题参数，不能把类已安装当作所有组合均兼容。
- 参数从类的 ParameterSet 和头部注释核实；没有覆盖要求时用 params: []。同类的不同配置写唯一 label，baseline 使用 label。
- 当前主要覆盖静态多目标优化。单目标、多任务、动态或其他特殊协议先核对终止、结果保存和指标含义，不宣称全面支持。

## 路径与配置

- `<PLATEMO>` 是包含 platemo.m 的目录，发行包可能多一层 PlatEMO/；也可设置 PLATEMO_ROOT。
- `<SCRIPTS>` 是本文件旁的 scripts/；`<PY>` 是结果解析解释器。算法所用解释器由适配器另行核对，不能混为一谈。
- 每次 run 新建 Experiments/<experiment_id>/，保存 config、manifest、日志和独立 Data。已存在的编号拒绝覆盖，不删除旧目录复用编号。
- experiment_root 可覆盖输出根目录，相对路径以配置文件目录为基准。每轮使用独立配置文件，避免覆盖其他任务配置。
- 新结果按 manifest 收集，不扫描平台旧 Data。

必填字段为 algorithms、problems、N、maxFE、runs、metrics、save_count。问题指定 class、M，可选 D、params；D 省略或为 0 时用问题默认值。save_count 必须大于 0。可建议 N=100、metrics=IGD,HV，但需明确实际协议；约束研究可加 Feasible_rate。

seeds 为不重复 uint32 整数列表，长度等于 runs；省略时使用 0 到 runs-1。同一问题的第 r 次运行在各算法间共享 seed。版本重跑保留整份 seed 列表，不删除失败 seed。

自定义指标在 metric_directions 中声明 min/max，已知方向不可覆盖，未知方向不可猜测。迭代 policy 的指标也需预先声明 direction，见 [迭代判断规则](references/iteration-decisions.md)。

assets/multiobjective_smoke.json 仅用于连通性验证；assets/lsmop_standard.json 仅在选定大规模研究时使用。示例值不能成为未说明的默认协议。

## run

1. 确认算法、问题已安装且组合兼容，明确完整配置和预算。耗时明显超出已有授权范围时再确认。
2. 查看 `<SCRIPTS>/adapters/registry.json`。匹配到算法或声明 adapter/required_capabilities 时，按 [适配器说明](references/runtime-adapters.md) 读取对应 reference；普通算法不加载无关扩展文档。
3. 保留已有实验，写入本轮配置。不能修改算法来掩盖依赖或适配器错误。
4. 在平台目录执行：

```text
matlab -batch "addpath('<SCRIPTS>'); run_platemo_batch('<CONFIG>');"
```

5. 检查 BATCH_SUMMARY、退出状态和 manifest，失败时报告相关 run、日志与诊断，不比较坏数据。记录输出的 MANIFEST 用于后续比较。

运行器在问题构造前设置 MATLAB twister，直接通过平台构造器和 Algorithm.Solve 运行，避免入口重新随机播种。沿用平台指标和 result，结束/失败后恢复调用方随机状态。参考点算法或问题可能调整 N、M、D，报告实际值。

通用成功不能证明所有内部机制和外部随机源已验证，报告 verification_scope 的实际范围。适配器仅提供声明范围内的证据，不改变算法搜索策略；不能为通过检查擅自切换算法模式。

## compare

```text
<PY> <SCRIPTS>/parse_results.py --manifest <EXPERIMENT>/manifest.json --baseline NSGAIII --json <EXPERIMENT>/metrics.json
<PY> <SCRIPTS>/parse_results.py --experiment "old=<OLD>/manifest.json" --experiment "new=<NEW>/manifest.json" --baseline old/NSGAII --json <NEW>/iteration_metrics.json
```

--algorithms 支持类名、label 或完整标签，--problems 按问题类名筛选。展示每个问题 M/D、各指标 mean +/- std 和 n，不合并不同问题尺度。--metric-directions CustomScore=max 可声明自定义方向，不能与实验声明冲突。

严格校验包含：完成状态、运行成员、文件 hash、预算、save_count、问题参数、问题/平台/指标源码、最终指标、随机性、配对 seed 及启用的适配器。算法源码及参数允许不同，其他协议不一致时停止比较。

指标只取序列最后一项，必须是有限实数。NaN/Inf 不用早期值替代，不删除无效运行，不临时估算 IGD/HV。所有系列覆盖相同问题 M/D，baseline 覆盖每个问题和指标。每组至少 2 次有效运行，--min-runs 可提高门槛但不保证检验能力。

失败退出码 2、insufficient_evidence、can_iterate=false，不生成排名或显著性结论，失败也更新 JSON。先处理 validation.issues。--preview 仅诊断预览，不能用于迭代；只有一次样本时 std 为 null。

新实验按 seed 对齐做双侧 Wilcoxon signed-rank，默认 α=0.05，差值分布需满足对称性假设。+/- 来自配对差值方向，= 表示未检出差异，不表示等价；全零差值 p=1。小样本不保证足够检验能力，同 seed 也不保证不同算法随机轨迹相同。

无清单历史数据只在用户要浏览时显式使用 --allow-legacy，说明来源未验证，不用于 iterate。历史结果不补造 seed 或诊断。没有算法适配器的普通 MATLAB 算法可完成通用比较，但不能宣称已检查未监测机制。

## iterate

只做一轮，目标为用户点名算法；目标不清楚先明确，不改其他算法。

1. 完成严格 compare 并指定 baseline。仅退出码 0 且 can_iterate=true 时继续；确认 verification_scope 覆盖本轮研究依赖的机制。
2. 读取 [迭代判断规则](references/iteration-decisions.md)，明确主指标、最小改善、退步容限、改善问题比例、最少次数和 α。用 prepare 锁定旧清单、完整问题集和 seeds，示例数值不会自动成为标准。
3. 备份本轮将改动的源文件至 `<OLD>/source_backup/<本轮编号>/`，备份失败则停止。保留旧实验与清单。
4. 只改一个机制或明确 bug，说明假设及预期影响。不改问题、指标或预算来让结果变好。
5. 候选配置保持完整问题、预算及 seed 列表，增加 iteration_plan 路径，建立新 experiment_id；仿真前保存方案原文和 hash。
6. 展示前后 compare，再执行 evaluate。can_iterate 是数据门槛；can_apply=true 且 keep 才确认保留，revert 才恢复本轮源码。恢复前确认没有他人新修改。insufficient_evidence 保持待定，不因不显著自动回退。
7. 报告改动、三态结论及触发的问题/指标/门槛和校正后 p 值。停止本轮，不自动继续。补样本需新方案并完整重跑配对实验；多轮调参最终用独立留出 seed/问题验证。
