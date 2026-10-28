# Issue to Merge

[English](README.md) | [简体中文](README.zh-CN.md)

把明确指定的 GitHub Issue 推进到实现、审核、PR、合并和清理。每个 Issue 使用独立的运行时执行上下文和 worktree，整个过程复用同一个实现 worker。

## 安装和准备

将包含 `SKILL.md` 的完整目录安装到当前运行时的技能目录。Codex 可以用 `$skill-installer` 从本仓库安装。

- Python 3.10+、Git、已登录的 GitHub 集成或 `gh`。
- 目标仓库的测试命令，以及本次 Issue 的提交、PR、合并和清理授权。
- 选择 TypeSafe Judge 路由时，需要环境变量 `TYPESAFE_API_KEY` 并启用每轮评估；不要把密钥写入提示词或仓库。

开发目录和安装目录是两个副本。修改开发目录不会自动更新安装目录；更新时应一起同步技能文件和引用，保留目录外的用户配置与 Issue 状态。

## 使用

普通模式（默认）：

```text
$issue-to-merge 按顺序处理 owner/repo 的 #123、#127，完成实现、提交、PR、合并和清理。
```

快速模式：

```text
$issue-to-merge quick mode: owner/repo #123，完成实现、提交、PR、合并和清理。
```

| 选项 | 行为 |
| --- | --- |
| `full`，默认 | 每次本地修复后重新独立审核，直到通过或达到上限。 |
| `quick` | 至少一次独立审核；之后只有行为或数据契约发生实质变化才再审核。 |
| `Copilot auto`，默认 | 能用就请求；确认不可用或等待超时后记录原因，并在本 Issue 内关闭。 |
| `Copilot off` | 不请求、不等待 Copilot；仍检查其他反馈和当前 HEAD 的 CI。 |

Copilot 与交付模式是两个独立选项。例如在任一调用后加上“Copilot off”。两种模式都只在初次提交 PR 时请求一次 Copilot；后续修复和推送不再请求。保留原反馈快照，照常完成必要的本地审核和新 HEAD 的 CI。

两种模式都保留本地审核、所配置的 Judge、CI 和分支保护；只有选中严格策略的 TypeSafe 路由时才执行相应评估。达到审核上限后，完成必要判断和最终修复、验证后提交，不再启动下一轮本地审核，也不把最终修复记成 reviewer PASS。远程 comments 必须通过与本地审核相同的 finding 标准；未解决 thread 必须为零。

## 模型配置

交付模式与实现难度分开选择。`full/quick` 决定审核流程；`simple/normal/complex/extreme` 决定 worker 配置。角色、模型和推理强度见 [模型配置指南](references/model-configuration.md) 和 [Codex JSON](config/runtimes/codex.json)。用户和项目指定的配置优先；每个 Issue 的 worker 选定后保持不变。

## 运行时兼容性

使用当前版本附带的适配器和配置，不混用其他版本的命令或 JSON 格式：[Codex](references/codex-runtime.md)、[Hermes](references/hermes-runtime.md)及其 [profile 指南](references/hermes-profiles-kanban.md)。Codex 使用独立 top-level task；每个 Issue 完成后核实子代理已停止，再结束当前上下文。需要关闭当前 Issue 任务的运行时应先完成关闭，再开始下一个。

高级配置和上下文约定见 [运行时选择](references/runtime-selection.md) 与 [上下文管理](references/context-management.md)。

## 需要 hook 吗

不需要。技能由明确调用启动，状态脚本和 CI 执行流程检查。本技能不要求额外的 Stop、pre-commit 或 pre-push hook。

## 设计边界

仅咨询、代码评审和未授权的 Issue 不启动完整交付。状态文件保存在目标 checkout 之外；命令用法见 `python scripts/review_cycle.py --help`。

详细规则：[SKILL.md](SKILL.md)、[quick 模式](references/quick-mode.md)、[Copilot 选项](references/copilot.md)。

版本准备与升级说明：[v0.8.0](docs/releases/v0.8.0.md)。

MIT License.
