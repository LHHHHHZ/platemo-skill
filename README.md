# PlatEMO 实验技能

给编程 Agent 用的 PlatEMO 批量实验技能。这个目录不是 PlatEMO 平台本身。

技能正文只有一份：`SKILL.md`。仓库里放了两份相同内容，因为不同 Agent 扫描的目录不一样。

| 目录 | 谁会读 |
| --- | --- |
| `.agents/skills/platemo/` | Codex、Cursor、Gemini CLI、GitHub Copilot、Cline、Warp |
| `.claude/skills/platemo/` | Claude Code。Cursor 和 Copilot 也会读这里 |

Codex 的旧安装位置 `~/.codex/skills/platemo/` 仍然可用。OpenCode 用 `.opencode/skills/platemo/`，把上面任意一份 `platemo` 文件夹拷过去即可。

## 安装

任选一种。

项目内：把 `.agents/skills/platemo` 和 `.claude/skills/platemo` 复制到 PlatEMO 仓库根目录下的同名路径。用哪个 Agent，就至少复制它会读的那一份。

用户目录：把 `platemo` 文件夹复制到 `~/.agents/skills/platemo` 或 `~/.claude/skills/platemo`。这样所有项目都能用。

然后安装 Python 依赖：

```text
pip install -r requirements.txt
```

需要 MATLAB R2019a 及以上，因为实验通过 `matlab -batch` 启动。PlatEMO 本身要求 R2018a 及以上。

脚本在技能目录的 `scripts/` 里，不要求先拷进 PlatEMO。运行前让工作目录处于包含 `platemo.m` 的那一层；外层若只看到 `PlatEMO/platemo.m`，就进入里面的 `PlatEMO` 目录。也可以设置环境变量 `PLATEMO_ROOT`。

## 示例

`examples/lsmop_standard.json` 与技能内的 `assets/lsmop_standard.json` 相同：LMOCSO 与 NSGAII，LSMOP1–LSMOP9，M=3，D=500，10 次重复，100000 次评价。算法类名按自己的实验替换。

每次批量运行会新建 `PlatEMO/Experiments/<experiment_id>/`，其中包含配置快照、结果清单、日志和独立的 `.mat` 结果。编号默认自动生成，也可在配置中指定 `experiment_id`；已存在时拒绝运行，避免覆盖旧实验。可选 `experiment_root` 用于自定义实验根目录，相对路径以配置文件所在目录为基准。

运行命令保持不变。运行器通过平台支持的 `outputFcn` 保存结果，保留 PlatEMO 的 `result`、`metric` 和指标计算；不向公共 `Data/<算法>/` 写入批处理结果。日志输出 `EXPERIMENT_ID` 和 `MANIFEST`，后续使用这份清单比较：

```text
python <技能目录>/scripts/parse_results.py --manifest <实验目录>/manifest.json --baseline NSGAII --json <实验目录>/experiment_metrics.json
```

清单记录每次运行的文件、SHA-256、参数、实际 N/FE、算法与问题源码以及算法目录中已有预训练权重的 hash。比较器只读取清单明确引用的结果，校验完整性和实验协议；算法参数/版本允许不同，N、maxFE、save_count、问题参数及问题/平台/指标源码不一致时拒绝合并比较。

同一算法的参数变体使用唯一 `label`：

```json
{"class": "SET_NSGAIII", "label": "online", "params": [2, 20]}
```

比较两个版本：

```text
python <技能目录>/scripts/parse_results.py --experiment "old=<旧实验>/manifest.json" --experiment "new=<新实验>/manifest.json" --baseline old/SET_NSGAIII
```

`--algorithms` 可按类名、算法 label 或 `old/SET_NSGAIII` 这样的完整标签筛选。各实验的样本单独统计，不会合并。

旧的 `--data-dir` 和 `--series` 模式保留，但必须显式加 `--allow-legacy`，输出会提示来源未验证，仅用于浏览历史数据，不作为自动迭代依据。

## 指标有效性与证据不足

比较默认严格校验最终指标：取序列最后一项，最后一项为 NaN/Inf 时不回退到早期值。缺失指标、无效最终值、无法读取的文件、重复运行或 baseline 未覆盖全部问题/指标时，拒绝生成优劣结论。每个请求指标至少需要 2 次有效运行；可通过 `--min-runs 5` 等选项提高门槛，最低不能小于 2。这个门槛不保证统计检验有足够能力。

数据有效时退出码为 0；证据不足时退出码为 2，并输出 `INSUFFICIENT_EVIDENCE`。指定 `--json` 后，即使比较失败也会写入诊断报告，避免误读旧的成功报告：

```json
{
  "status": "insufficient_evidence",
  "comparison_ready": false,
  "can_iterate": false,
  "validation": {
    "issues": [{"code": "invalid_final_metric", "algorithm": "SET_NSGAIII", "problem": "LSMOP1", "metric": "IGD", "run": 2}]
  }
}
```

报告还包含每组的预期运行数和各指标有效次数。只有完整、有效、有 baseline 的清单比较才能给出 `can_iterate=true`；单算法摘要、历史目录浏览和预览都不能用于自动迭代。`can_iterate` 是数据门槛，仍需检查算法依赖是否降级，及改动本身是否值得保留。

需要排查部分数据时，可以预览：

```text
python <技能目录>/scripts/parse_results.py --manifest <实验目录>/manifest.json --preview --json <实验目录>/diagnostics.json
```

预览会显示可用数据的统计摘要，但不标记最优、不做显著性检验，`can_iterate` 始终为 false；数据不足时仍返回退出码 2。只有 1 次样本时，标准差显示 n/a，JSON 中为 null。

回归测试：`python -m unittest discover -s tests -p "test_*.py" -v`。真实 MATLAB 保存验证位于 `tests/test_batch_runner.m`，传入平台目录和新建的临时输出目录后执行，只使用小预算。

## 许可

技能文本和 `scripts/` 使用 MIT 许可证，见 `LICENSE`。

PlatEMO 平台的版权属于 BIMK。使用平台发表成果时，须致谢 PlatEMO，并引用：

Ye Tian, Ran Cheng, Xingyi Zhang, and Yaochu Jin, PlatEMO: A MATLAB Platform for Evolutionary Multi-Objective Optimization [Educational Forum], IEEE Computational Intelligence Magazine, 2017, 12(4): 73-87.
