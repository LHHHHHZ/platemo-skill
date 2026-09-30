---
name: platemo
description: "Run or compare PlatEMO experiments and iterate one algorithm from IGD/HV. Use for PlatEMO, LSMOP, SMOP, LSCM, or batch multi-objective runs. 在 PlatEMO 上批量运行算法、对比指标并迭代算法。"
license: MIT
compatibility: MATLAB R2019a+ and Python with numpy and scipy. Scripts are in scripts/ next to this file.
---

用用户正在使用的语言回复。日志和命令保持英文。

这个技能驱动 PlatEMO 实验：批量运行任意已安装算法，读取 `Data` 里的指标，判断优劣，并在用户要求迭代时只改被点名的那个算法。默认测试集是大规模多目标问题。不要启动无参数的 `platemo()`，那会打开 GUI。

调用技能时用户给出的文字里可以有：

- 子命令：`run`、`compare`、`iterate`。没写时，要跑实验用 `run`，只看已有数据用 `compare`。
- `--quick` / `--standard` / `--full`：只决定测试集和预算。显式选项覆盖预设。
- `--algorithms`：逗号分隔的类名。没有就问，不要默认成某一个算法。
- `--problems`：逗号分隔的问题类名。
- `--M`、`--D`、`--N`、`--maxFE`、`--runs`、`--metrics`、`--baseline`、`--config`。

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
- 结果在 `<PLATEMO>/Data/<算法类名>/<算法类名>_<问题类名>_M<实际M>_D<实际D>_<run>.mat`。相同 `run` 会覆盖旧文件。`Data` 下以下划线开头的目录是备份。

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
5. 启动后只报告配置摘要和 `batch_run.log` 的位置。不要假装已经看到指标。
6. 结束后先看 `BATCH_SUMMARY`。`fail` 不为 0 就摘出 `FAIL:` 行，不要对比坏数据。日志表明算法依赖没有初始化并已退回另一种搜索时，这次对比无效。
7. 日志有效后再做 compare。

批量运行器是顺序执行的，不要再包一层 `parfor`。

## compare

不要改算法、问题或配置。把类名换成这次配置里的名字：

```text
<PY> <SCRIPTS>/parse_results.py --data-dir <PLATEMO>/Data --metrics IGD,HV --algorithms LMOCSO,NSGAII --baseline NSGAII --json <PLATEMO>/experiment_metrics.json
```

同一算法的备份和新结果用重复的 `--series`，不要和 `--data-dir` 混用：

```text
--series "old=<PLATEMO>/Data/_backup_<时间戳>/<算法类名>" --series "new=<PLATEMO>/Data/<算法类名>" --series "base=<PLATEMO>/Data/<基线类名>" --baseline base
```

向用户报告每个问题、每个指标的 `mean +/- std` 和 `n`，并带上 M、D。`*` 是该行均值最优。IGD、GD 越小越好；HV 越大越好。`+`、`-`、`=` 是相对 baseline 的双侧 Mann-Whitney 检验，默认 α=0.05。`na` 表示任一侧少于 2 次运行。runs 小于 5 时说明显著性只能当线索。按问题指出落后的位置，不要只报一个平均名次。

`files_used` 为 0 或缺少请求的指标时，这些 `.mat` 不是用 `save>0` 和 `metName` 生成的。不要自己用目标值临时估算 IGD 或 HV。

## iterate

只做一轮，然后停下来等用户决定。被修改的算法是用户点名的那个；没点名时，是这次对比中准备改进的那个。

1. 先完整做一次 compare。没有可用指标就停止。
2. 只把落后的问题当成修改依据。用 `classdef` 定位该类的 `.m`，只在需要时读同目录里的辅助文件。不要顺手重构，也不要改别的算法。
3. 修改前把源文件复制到 `<SCRIPTS>/backups/<yyyyMMdd-HHmmss>/`。把配置里每个算法的结果目录复制到 `<PLATEMO>/Data/_backup_<同一时间戳>/<算法类名>/`。备份失败就不要重跑。
4. 只改一个机制或一个明确的 bug。说明改了什么、期望哪些问题变好、什么结果算退步。
5. 用同一份配置再走 run。不要顺便换算法、问题、D 或 maxFE。
6. 用 `--series` 把备份、新结果和基线放在同一张表里。改进不足或落后问题变多时，用源文件备份覆盖回去，并说明已回退。不要删除 `Data/_backup_*`。
7. 给出改动、保留还是回退、哪些问题变好或变差，以及下一轮只值得试什么。不要自动开始下一轮。
