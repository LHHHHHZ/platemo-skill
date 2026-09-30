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

相同 `run` 编号会覆盖 `Data/` 里的旧结果。

## 许可

技能文本和 `scripts/` 使用 MIT 许可证，见 `LICENSE`。

PlatEMO 平台的版权属于 BIMK。使用平台发表成果时，须致谢 PlatEMO，并引用：

Ye Tian, Ran Cheng, Xingyi Zhang, and Yaochu Jin, PlatEMO: A MATLAB Platform for Evolutionary Multi-Objective Optimization [Educational Forum], IEEE Computational Intelligence Magazine, 2017, 12(4): 73-87.
