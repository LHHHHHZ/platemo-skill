---
name: platemo
description: "Run or compare PlatEMO experiments and iterate one algorithm from IGD/HV. Use for PlatEMO, LSMOP, SMOP, LSCM, or batch multi-objective runs. 在 PlatEMO 上批量运行算法、对比指标并迭代算法。"
license: MIT
---

用用户正在使用的语言回复。日志和命令保持英文。

需要 MATLAB R2019a+，以及安装 numpy、scipy 的 Python。配套脚本在本文件旁的 `scripts/` 目录。

运行 `SET_NSGAIII` 时需要支持 `pyenv` 的 MATLAB（R2019b+），以及该算法 `.venv/Scripts/python.exe` 中的 numpy、scipy、torch。结果解析所用的 `<PY>` 可以是另一解释器；仅在 `<PY>` 中安装依赖不能证明 MATLAB 的算法依赖可用。

这个技能驱动 PlatEMO 实验：批量运行任意已安装算法，按实验清单读取指标，判断优劣，并在用户要求迭代时只改被点名的那个算法。默认测试集是大规模多目标问题。不要启动无参数的 `platemo()`，那会打开 GUI。

调用技能时用户给出的文字里可以有：

- 子命令：`run`、`compare`、`iterate`。没写时，要跑实验用 `run`，只看已有数据用 `compare`。
- `--quick` / `--standard` / `--full`：只决定测试集和预算。显式选项覆盖预设。
- `--algorithms`：逗号分隔的类名。没有就问，不要默认成某一个算法。
- `--problems`：逗号分隔的问题类名。
- `--M`、`--D`、`--N`、`--maxFE`、`--runs`、`--metrics`、`--baseline`、`--config`。
- 比较已有实验时提供 `manifest.json` 路径；比较多个版本时为每份清单指定不同的实验标签。
- 比较可用 `--min-runs` 提高每项指标所需的有效运行数，默认 2；`--preview` 只用于诊断预览。

算法和问题都用 `classdef` 后面的类名，不要用文件夹名。`NSGA-III` 文件夹里的类是 `NSGAIII`，`MOEA/D` 是 `MOEAD`。不确定时搜索 `classdef`。

`--D` 为 `0` 或不传时用问题默认值，不要把 0 写进 `platemo` 的 `'D'`。`--N` 默认 100。使用参考点的算法可能通过 `UniformPoint` 改写 N，这不是错误。`--metrics` 默认 `IGD,HV`。约束测试集（如 LSCM）再加 `Feasible_rate`。`--baseline` 未指定时用算法列表里的最后一个。算法构造参数只在用户明确给出，或该类文件顶部有 `名字 --- 默认值 --- 含义` 且用户要求覆盖时写入 `params`，否则用 `[]`。

## 大规模测试集

用户未指定问题时用大规模套件，不要改用 DTLZ、ZDT 或 WFG。

| 套件 | 类名 | 未写 D 时 | 说明 |
| --- | --- | --- | --- |
| LSMOP | `LSMOP1`–`LSMOP9` | M=3，D=100×M | 常用 D=300、500、1000 |
| SMOP | `SMOP1`–`SMOP8` | M=2，D=100 | `params` 第一项是稀疏度 theta，默认 0.1 |
| LSCM | `LSCM1`–`LSCM12` | M=2，D=100 | D 会被取整，以结果文件名中的 D 为准 |
| TREE | `TREE1` 起 | M 固定为 2，D=T×3 | 不要强行改 M |

有些问题会在 `Setting` 里改写 M 或 D。比较时以结果文件名里的 M、D 为准。

| 预设 | 问题 | M | D | runs | maxFE |
| --- | --- | --- | --- | --- | --- |
| quick | LSMOP1, LSMOP5 | 3 | 300 | 3 | 50000 |
| standard | LSMOP1–LSMOP9 | 3 | 500 | 10 | 100000 |
| full | LSMOP1–LSMOP9，以及 SMOP1–SMOP8 | LSMOP 为 3，SMOP 为 2 | 1000 | 20 | 200000 |

这些是工程默认值，不是论文协议。用户给出的数字优先。`full` 先算出“算法数 × 问题数 × runs”并说明耗时，用户确认后再启动。未指定预设、问题、maxFE、runs 时用 quick，并写明实际配置。

示例配置在本技能的 `assets/lsmop_standard.json`。算法类名按用户的实验替换。

## 路径

- `<PLATEMO>`：包含 `platemo.m` 的目录。发行包若是外层套着 `PlatEMO/` 文件夹，就用里面那一层。
- 本技能的 `scripts/run_platemo_batch.m` 和 `scripts/parse_results.py` 与本文件同级。
- 配置写到 `<PLATEMO>/../experiment_config.json`；若 `<PLATEMO>` 本身就是仓库根，就写到 `<PLATEMO>/experiment_config.json`。
- 每次 run 新建 `<PLATEMO>/Experiments/<experiment_id>/`，保存 `config.json`、`manifest.json`、`batch_run.log` 和 `Data/a<算法序号>_p<问题序号>/*.mat`。清单列出本次运行的结果和来源，比较只读清单中的文件。
- `experiment_id` 默认自动生成。用户可在配置中指定，但已存在时拒绝运行。不要删除旧目录来复用编号。
- 配置可选 `experiment_root`，覆盖实验根目录；相对路径以配置文件所在目录为基准。
- 同一算法的不同参数写为多条 algorithms，每条指定唯一 `label`，例如 `{"class":"SET_NSGAIII","label":"online","params":[2,20]}`。默认 label 是类名，重复 label 会被拒绝。baseline 使用 label。
- 平台原有 `Data/` 目录供历史数据浏览；新运行器使用自定义 outputFcn 直接保存独立结果，沿用平台的 result、metric 和指标计算。

配置示例：

```json
{
  "algorithms": [
    {"class": "LMOCSO", "params": []},
    {"class": "NSGAII", "params": []}
  ],
  "problems": [
    {"class": "LSMOP1", "M": 3, "D": 500}
  ],
  "N": 100,
  "maxFE": 100000,
  "runs": 10,
  "metrics": ["IGD", "HV"],
  "save_count": 6
}
```

`save_count` 必须大于 0。同一问题的不同 M 或 D 写成多条 `problems`。

## run

1. 解析用户文字并写出配置。算法未给出时先问。已给出算法，或用户说直接跑且预设已知时，用两三句话确认算法、问题、M、D、N、maxFE、runs，然后启动。
2. 确认 `matlab` 在 PATH 中。Windows 用 `where matlab`，macOS 和 Linux 用 `command -v matlab`。没有就停止。`matlab -batch` 需要 R2019a 及以上。
3. 先确定能执行 `import numpy, scipy` 的 Python，记为 `<PY>`。Windows 上若 `python` 是 Microsoft Store 占位程序，改用 `py -3`。
4. 把 `<SCRIPTS>` 换成 `run_platemo_batch.m` 所在目录。在后台启动，不要为了等实验结束而把命令超时缩到几分钟。当前 Agent 不能后台执行时，给出这条命令并说明日志位置：

```text
matlab -batch "cd('<PLATEMO>'); addpath('<SCRIPTS>'); run_platemo_batch('<CONFIG>')"
```

路径含空格时保持 MATLAB 单引号，斜杠用 `/`。
5. 启动后只报告配置摘要，以及日志中的 `EXPERIMENT_ID`、`MANIFEST` 和该实验 `batch_run.log` 的位置。不要假装已经看到指标。后续比较使用这份清单，不要猜测哪个目录是最新实验。
6. 结束后先看 `BATCH_SUMMARY`。`fail` 不为 0 就摘出 `FAIL:` 行及每次运行的诊断，不要对比坏数据。`SET_NSGAIII` 会自动验证依赖、真实模式、训练步数、权重和预测解注入；检测到降级就中止该次运行，清单标为 failed，批处理返回非零。其他算法的依赖日志仍需人工检查。
7. 日志有效后再做 compare。

批量运行器是顺序执行的，不要再包一层 `parfor`。

`SET_NSGAIII` 的 `runtime_diagnostics` 同时保存在结果来源、清单和 `Data/a<算法序号>_p<问题序号>/run_<r>_diagnostics.json`，该目录的 `run_<r>.log` 保留逐次日志。诊断记录 MATLAB 实际使用的 Python 与依赖版本、请求/实际 TRAIN、加载权重路径及 SHA-256、实际训练步数、预测成功/失败次数、GA 回退次数、注入解数量与留存数量。临时监测接口运行结束后恢复，不修改算法源码或子代比例。

TRAIN=0 必须真正加载权重且不能在线训练；TRAIN=1 必须加载权重并执行微调，缺失/不兼容权重后的从零训练视为模式不一致。只有用户明确要在线训练时才用 TRAIN=2，不要为让实验通过擅自改模式。Python 预测返回成功还不够，必须有 MATLAB 的真实预测解注入记录。没有触发预测或训练时标为 `not_exercised`；先检查 maxFE、实际 N、GW 和每 5 代的预测间隔，调整配置重新运行。预测解留存数为 0 仍是有效机制运行，效果由指标判断。

## compare

不要改算法、问题或配置。使用本次 run 输出的清单，算法筛选和 baseline 使用配置中的 label（未指定 label 时用类名）：

```text
<PY> <SCRIPTS>/parse_results.py --manifest <EXPERIMENT>/manifest.json --metrics IGD,HV --algorithms LMOCSO,NSGAII --baseline NSGAII --json <EXPERIMENT>/experiment_metrics.json
```

比较修改前后两个实验，用重复的 `--experiment`。输出标签是 `<实验标签>/<算法label>`，因此可直接检验新版本相对旧版本的变化：

```text
<PY> <SCRIPTS>/parse_results.py --experiment "old=<OLD>/manifest.json" --experiment "new=<NEW>/manifest.json" --metrics IGD,HV --baseline old/SET_NSGAIII --json <NEW>/iteration_metrics.json
```

比较默认严格校验：每个结果必须包含所有请求的指标；最终指标必须是有限实数，且每项指标至少有 `--min-runs` 次有效运行（默认 2，不能设为 1）。只取指标序列的最后一项；最后一项是 NaN/Inf 时，不用早期有效值替代。同一张比较表中的系列必须覆盖相同的问题 M/D，指定 baseline 时它必须覆盖每个问题和每个指标。

无效最终指标、缺失指标、缺失 baseline、有效样本不足、无法读取的文件或重复运行，会返回退出码 2，输出 `INSUFFICIENT_EVIDENCE`，不生成最优标记或显著性检验。指定 `--json` 时失败也生成诊断报告，覆盖旧报告。报告中 `status=insufficient_evidence`、`can_iterate=false`，`validation.issues` 列出原因、相关文件和运行编号；`validation.groups` 给出每项指标的有效次数。不要据此判优劣、修改算法或自动回退；先报告缺失/无效位置，再补齐或重新运行实验。

只想查看可用的部分数据时加 `--preview`。预览不显示最优标记、不做显著性检验，`can_iterate` 始终为 false；数据不足时仍返回退出码 2。仅 1 次有效样本时，std 显示 n/a（JSON 为 null）。不要把预览用于 iterate。

有效比较向用户报告每个问题、每个指标的 `mean +/- std` 和 `n`，并带上 M、D。`*` 是该行均值最优。IGD、GD 越小越好；HV 越大越好。`+`、`-`、`=` 是相对 baseline 的双侧 Mann-Whitney 检验，默认 α=0.05；`=` 表示未发现显著差异，不表示两者等价。最少 2 次是数据门槛，不保证统计检验有足够能力。runs 小于 5 时说明显著性只能当线索。按问题指出落后的位置，不要只报一个平均名次。

清单模式会检查实验完成状态、运行成员、结果文件 SHA-256，以及相同问题 M/D 下的 N、maxFE、save_count、问题参数、问题源码和平台/指标源码是否一致。协议不一致时停止比较；算法参数和算法源码可以不同，这是算法或版本对比的目的。实际 N、FE、算法目录源码和已有预训练权重的 hash 保存在来源记录中，JSON 报告包含所用清单和记录。

比较器还会核对每条 `SET_NSGAIII` 的运行机制诊断。缺少诊断、模式不一致、加载权重未被源码清单的 hash 验证、预测/训练没有实际执行或发生 GA 回退时，即使 IGD/HV 都有效也返回退出码 2，禁止排名、显著性结论和 iterate。历史 SET 清单缺少这些证据时，需要重新运行才能用于严格比较；不要伪造诊断。

没有清单的历史数据，仅在用户明确要浏览历史结果时使用 `--data-dir ... --allow-legacy` 或 `--series ... --allow-legacy`，并说明预算、参数和版本未验证。不要把这种汇总用于 iterate，也不要伪造清单给旧文件补上未知来源。

诊断显示指标缺失时，检查是否以 `save>0` 和相应 `metName` 保存；最终指标无效时，检查仿真和指标计算。不要自己用目标值临时估算 IGD/HV，也不要删掉无效运行来让比较通过。

## iterate

只做一轮，然后停下来等用户决定。被修改的算法是用户点名的那个；没点名时，是这次对比中准备改进的那个。

1. 先完整做一次严格 compare，指定 baseline。仅退出码 0 且 JSON 中 `can_iterate=true` 时继续；这包含 SET 的运行机制校验，其他算法仍需检查依赖降级日志。`insufficient_evidence`、预览或无 baseline 的统计摘要都不能用于修改算法。
2. 只把落后的问题当成修改依据。用 `classdef` 定位该类的 `.m`，只在需要时读同目录里的辅助文件。不要顺手重构，也不要改别的算法。
3. 记录旧实验清单路径，把准备修改的源文件复制到 `<OLD>/source_backup/<yyyyMMdd-HHmmss>/`。旧实验结果目录保持原样，无需再复制整个 Data。源码备份失败就不要修改或重跑。
4. 只改一个机制或一个明确的 bug。说明改了什么、期望哪些问题变好、什么结果算退步。
5. 用相同实验配置再走 run。若原配置有显式 experiment_id，仅删除或更换该字段以建立新实验。不要顺便换算法、问题、D 或 maxFE。记录新清单路径。
6. 用 `--experiment old=... --experiment new=...` 把修改前、新结果和配置里的基线放在同一张表里。先检查比较退出码及 can_iterate；证据不足时停止优劣判断并报告原因，不自动以“变差”为由回退。比较有效后，改进不足或落后问题变多时，用源文件备份恢复源码，并说明已回退。两个实验及其清单都保留，回退源码不改变历史结果的归属。
7. 给出改动、保留还是回退、哪些问题变好或变差，以及下一轮只值得试什么。不要自动开始下一轮。
