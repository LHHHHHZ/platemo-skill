# 预先登记迭代判断规则

`parse_results.py` 的 `can_iterate` 是实验数据门槛。`decide_iteration.py` 负责另一个问题：本次改动是否满足预先声明的改善目标和退步约束。判断器只输出报告，不改算法源码。

## 运行前锁定

先根据任务明确规则，将 `assets/iteration_policy.example.json` 复制到本轮独立的 policy 文件再修改。示例中的 IGD、1%、50%、10 次、α=0.05 仅演示格式，不是通用推荐值，不会被脚本自动采用。

| 配置 | 含义 |
| --- | --- |
| primary_metric | 唯一主指标，必须包含在 metrics 中 |
| metrics | 全部受保护的指标，方向由已知指标定义确定；未知指标拒绝 |
| scale | relative：逐 seed 的改善量除以旧值绝对值；absolute：原始指标单位 |
| min_improvement | 仅主指标填写，必须为正；有证据表明改善超过此值才计为改善 |
| max_regression | 各指标允许的退步幅度，必须非负 |
| required_improved_fraction | 需改善的问题比例，范围 (0,1]，所需个数向上取整 |
| min_runs | 每个问题、指标所需完整配对次数，整数且至少 2；不是检验能力保证 |
| alpha | 整轮多重检验校正后的显著性门槛，范围 (0,1) |

relative 的 0.01 表示 1%；IGD 越小越好，HV 越大越好，改善统一记为正。旧值为 0 时相对变化无定义，返回证据不足；需要在新方案中预先使用有意义的绝对门槛，不用任意 epsilon 替代。门槛附近的机器舍入误差不算越过门槛。

```text
<PY> <SCRIPTS>/decide_iteration.py prepare --baseline <OLD>/manifest.json --algorithm SET_NSGAIII --policy <POLICY.json> --out <PLAN.json>
```

`--algorithm` 是旧实验中的精确 label。prepare 检查旧数据完整有效，保存旧清单 SHA-256、目标算法类/label、所有问题及 M/D、seed 列表和规则。方案文件已存在时拒绝覆盖。旧数据重复次数不够时，先按预定预算重新跑基准实验。

修改目标算法后，在候选运行配置中加入：

```json
{"iteration_plan":"E:/experiments/round_01/plan.json"}
```

这是配置的新增字段，其他必需字段仍按 run 填写。相对路径以配置文件目录为基准。运行器在仿真前把原始方案复制为实验目录的 `iteration_plan.json`，并把路径和 hash 写入配置快照与清单。不得只跑落后问题；完整测试集包含原本表现好的问题。

## 运行后判断

```text
<PY> <SCRIPTS>/decide_iteration.py evaluate --plan <PLAN.json> --candidate <NEW>/manifest.json --json <NEW>/iteration_decision.json
```

新旧 label 不同可提供 `--candidate-label`，算法类必须相同。判断器重新读取清单和结果，复用指标、协议、随机性、SET 机制检查；不接受人工写出的均值摘要。它核对旧清单未变、候选确实绑定了该方案、快照未变，以及完整问题/seed 覆盖。没有绑定方案的旧候选不能事后补登记。

每个问题、指标按 seed 计算改善量。对每个受保护指标检验改善是否高于负的退步容限，以及是否低于该边界；主指标另外检验改善是否超过最低改善幅度。使用移动门槛后的单侧 Wilcoxon signed-rank，所有问题、指标、方向的检验共同做 Holm 校正。结论还要求改善量中位数位于相应边界一侧。

| 输出 | 条件及后续行为 |
| --- | --- |
| keep | 足够比例的问题在主指标上超过改善门槛，且所有问题的所有受保护指标均有证据处于退步容限内；确认保留 |
| revert | 任一问题、任一受保护指标有证据表明退步超过容限；即使主指标改善也建议回退本轮源码 |
| insufficient_evidence | 样本/来源/覆盖不足、方案不一致，或改善/退步约束尚未得到支持；候选待定，不能自动回退或继续改算法 |

keep/revert 退出码为 0，`can_apply=true`；证据不足退出码为 2，`can_apply=false`。可读取 checks 中逐项的中位数改善量、门槛、原始/校正后 p 值、配对 seed 和判定。失败也覆盖输出报告，避免误读旧的 keep。源码恢复由 agent 按 SKILL 的备份规则执行，工具本身不执行 Git 或删除文件。

## 结论边界

不显著不等于“没有价值”，也不等于“没有退步”。小样本和多重校正可能无法证明任何方向，此时应输出待定。完全等于门槛也不算越过；容限为 0 时，与旧结果完全相同无法支持严格高于该边界。

Wilcoxon 假设配对改善量分布对称；相对变化可能不满足该假设，需要结合领域和样本设计判断适用性。它保护的是预登记的各问题指标分布位置，并不保证每个 seed 都不会变差。规则是当前实验协议内的工程接受标准，不代表全局最优或论文级泛化结论。[SciPy 文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html)

Holm 校正控制本轮全部检验的多重比较；不替代跨多轮调参的独立验证。不要反复查看结果后改变主指标、删问题、换 seed 或降低门槛。需要补样本时制定新方案，完整重跑新旧配对实验；最终使用预留且未参与修改决策的 seed/问题验证。[Holm 方法说明](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)
