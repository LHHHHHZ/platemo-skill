# PlatEMO 实验技能

面向 PlatEMO 的通用实验工具，让编程 Agent 批量运行算法、比较实验指标，并在用户要求时辅助完成一轮算法迭代。算法通过类名和参数配置接入，特殊依赖及内部机制通过可选适配器校验。

本仓库提供技能和实验脚本，PlatEMO 平台及待研究算法由使用者安装。当前流程主要面向静态多目标优化；单目标、多任务、动态优化等特殊实验协议需要另行验证适用性。

## 安装

将 `.agents/skills/platemo/` 或 `.claude/skills/platemo/` 复制到项目根目录下的对应位置，或安装到 Agent 的用户技能目录。两份技能内容一致，按所用 Agent 的发现路径选择。

基础环境为 MATLAB R2019a+、PlatEMO，以及装有 NumPy、SciPy 的 Python：

```text
pip install -r requirements.txt
```

普通 MATLAB 算法不要求安装算法扩展依赖。启用适配器时，再按对应文档准备环境。

## 快速运行

可以向 Agent 描述：

> 在 DTLZ2 上比较 NSGAII 和 NSGAIII，M=3、D=8、N=12、maxFE=24，运行 3 次，保存 IGD 和 HV。这次只验证运行流程。

等价配置见 [multiobjective_smoke.json](examples/multiobjective_smoke.json)。在包含 `platemo.m` 的平台目录执行：

```text
matlab -batch "addpath('<技能目录>/scripts'); run_platemo_batch('<配置文件绝对路径>');"
```

也可通过 `PLATEMO_ROOT` 指定平台目录，脚本无需复制进平台源码。该预算仅验证流程，不能据此宣称性能优劣。

每次运行新建 `Experiments/<experiment_id>/`，保存配置快照、manifest、日志和独立结果。已有编号拒绝覆盖；`experiment_root` 可指定输出根目录，相对路径以配置文件目录为基准。

## 选择问题与预算

先按研究目标选择问题族，再明确预算。`quick / standard / full` 表示所选问题族内的实验规模，不固定绑定某一套问题。

| 研究方向 | 可选问题族 |
| --- | --- |
| 常规多目标或多目标数 | DTLZ、ZDT、WFG 等兼容问题 |
| 大规模多目标 | LSMOP、SMOP 等 |
| 约束多目标 | 与算法约束处理及编码兼容的问题，必要时加入可行率 |

用户协议优先；研究方向不明确时先明确问题族，不自动转为大规模研究。M、D、编码和参数以具体类源码为准。原 [lsmop_standard.json](examples/lsmop_standard.json) 保留为可选的大规模预设。详见 [测试集与预算](.agents/skills/platemo/references/benchmarks.md)。

## 比较实验

使用运行器输出的清单，避免混入共享目录中的历史结果：

```text
python <技能目录>/scripts/parse_results.py --manifest <实验目录>/manifest.json --baseline NSGAIII --json <实验目录>/metrics.json
python <技能目录>/scripts/parse_results.py --experiment "old=<旧实验>/manifest.json" --experiment "new=<新实验>/manifest.json" --baseline old/NSGAII --json <新实验>/metrics.json
```

同一算法的不同参数配置使用唯一 label，baseline 可使用 label 或 `old/NSGAII` 这样的完整标签。例如，当前平台 MOEAD 首个参数为聚合函数类型，可用不同 label 区分；参数含义以安装的平台源码为准。

比较器检查完整运行成员、文件 SHA-256、预算、问题参数及问题/平台源码。每个最终指标必须为有限实数，NaN/Inf 不以早期值替代；有效重复次数最低为 2，`--min-runs` 可提高门槛但不保证检验能力。

证据不足返回退出码 2、`can_iterate=false`，不生成排名或显著性结论，失败也更新 JSON。`--preview` 仅显示可用统计，不能用于迭代。无清单的历史数据仅显式使用 `--allow-legacy` 浏览，来源未验证。

已知指标按平台定义判断方向，如 IGD 越小越好、HV 越大越好。自定义指标在实验配置中声明：

```json
{"metric_directions": {"CustomScore": "max"}}
```

也可在比较时指定 `--metric-directions CustomScore=max`。声明不能与已知指标或其他实验冲突。未知且未声明方向时停止判优，不猜测方向。指标由平台计算保存，脚本不临时估算缺失的 IGD/HV。

## 随机性与证据范围

配置支持 `"seeds":[11,22,33]`，长度等于 runs，每项是不重复的 uint32 整数；省略时使用 0 到 runs-1。运行器在问题构造前初始化 MATLAB twister，直接调用平台构造器和 `Algorithm.Solve`，结束后恢复调用方状态。

不同算法和前后版本按 seed 配对，比较采用双侧 Wilcoxon signed-rank，要求 seed 集合相同。检验需要配对差值分布对称；不显著不表示等价，小样本不保证有足够检验能力。

报告中的 `verification_scope` 区分通用 MATLAB 随机性与扩展能力。未使用适配器的普通算法仍可比较，但内部机制及外部随机源显示为未检查，不能声称全部行为已经验证。同 seed 也不保证跨硬件、跨依赖版本完全相同。

## 辅助迭代

先严格比较、备份目标源码，再用 `decide_iteration.py prepare` 锁定主指标、改善门槛、退步容限、完整问题集、seed 和样本要求。候选配置通过 iteration_plan 保存方案原文和 hash。

运行后 evaluate 重新校验结果，对配对改善量做门槛检验及 Holm 多重比较校正：

- keep：改善目标与完整测试集的退步约束均得到支持。
- revert：任一受保护问题/指标存在超过容限的明确退步。
- insufficient_evidence：来源、数据或统计证据不足，候选待定。

`can_iterate` 表示数据门槛通过，`can_apply` 表示可执行保留/回退建议。判断器不修改算法源码，也不执行 Git 操作。示例门槛不会自动成为标准，不能查看结果后临时调整。命令和统计假设见 [迭代判断规则](.agents/skills/platemo/references/iteration-decisions.md)。多轮调参后仍需独立留出实验。

## 可选适配器

适配器负责算法特有的依赖、内部机制和外部随机源。运行器与比较器使用同一本地注册表，清单记录所选适配器身份、版本、能力和相关源码 hash。

普通算法无需适配器；已声明或匹配的适配器不能静默跳过。所需能力缺失、扩展不可用或校验失败时明确停止。配置与开发接口见 [适配器说明](.agents/skills/platemo/references/runtime-adapters.md)。

## 测试

```text
python -m unittest discover -s tests -p "test_*.py" -v
```

通用测试覆盖实验隔离、指标、随机性、迭代判断及无扩展环境。`test_adapter_*` 单独覆盖算法扩展，真实依赖测试需要对应环境。MATLAB 通用验证见 test_batch_runner.m、test_seed_runner.m、test_iteration_runner.m、test_generic_runner.m，使用新的临时目录和小预算。

## 许可

技能文本和脚本使用 MIT 许可证，见 LICENSE。PlatEMO 平台版权属于 BIMK。使用平台发表成果时请按平台要求致谢并引用：

Ye Tian, Ran Cheng, Xingyi Zhang, and Yaochu Jin, PlatEMO: A MATLAB Platform for Evolutionary Multi-Objective Optimization [Educational Forum], IEEE Computational Intelligence Magazine, 2017, 12(4): 73-87.
