# Issue to Merge

[English](README.md) | [简体中文](README.zh-CN.md)

[![Validate](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml/badge.svg)](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

通过一套有证据、有限且可审计的多代理工作流，把指定的 GitHub Issue 推进为经过审查并已合并的 PR。

`issue-to-merge` 是一个可移植的 [Agent Skill](https://agentskills.io)，适用于支持可关闭顶层任务、子代理委派和 GitHub 操作的编程代理运行时。每个 Issue 都会获得全新的顶层任务以及隔离的分支/worktree；任务根代理就是 manager；整个 Issue 复用一个 implementation worker；每轮本地审查都创建全新的 reviewer；先发布 Draft PR；处理一次有明确边界的远程反馈窗口；验证合并确实关闭了 Issue；关闭当前 Issue 任务后才会开始下一个 Issue。

## 它强制保证什么

- 每次只处理一个 Issue，并始终从最新的远程默认分支开始。
- 每个 Issue 都使用一个全新的可关闭顶层任务；任务根代理就是 manager，不再创建嵌套 manager。
- 整个 Issue 只使用一个持续存在的 implementation worker，包括本地修复、远程反馈和 Issue 导致的 checks 修复。
- 行为变更采用 TDD，并运行聚焦测试及仓库要求的测试。
- 每轮本地审查都使用全新的只读 reviewer，最多十五轮。
- 默认只把现实可复现、直接影响 Issue 验收要求的功能、流程、数据契约和错误处理问题作为 finding；不接受推测性加固或抽象。
- PR 必须先处于 Draft 状态，再进入 Ready for review，并准确包含 `Closes #<issue>`。
- 只有一个十分钟的远程反馈窗口，统一覆盖 checks、reviews、threads、Issue comments 和 Copilot feedback。
- 远程 comments 必须通过与本地审核相同的 finding 标准，之后才能接受并修改。
- 每个行内 review thread 都必须有最终处理结论、在 GitHub 上标记为 resolved，并在合并前重新查询确认；未解决 thread 必须为零。
- 面向用户的进度和结果使用与用户一致的语言以及简短大白话；完整证据保留在内部报告中。
- 不绕过分支保护；存在有效 blocker 或未解决 review thread 时不得合并。
- 必须验证 Issue 已关闭，并按顺序清理远程分支、worktree 和本地分支。
- 必须验证当前 Issue 任务已经关闭，之后才能开始下一个 Issue。
- `scripts/review_cycle.py` 使用确定性的 JSON 状态机拒绝非法生命周期跳转。
- 首次使用时明确选择运行时和路由，并把选择保存在 skill 目录之外；每个 Issue 使用经过主机预检的固定策略快照。
- 选择分层 Codex 策略后，必须记录 worker 复杂度评估、实际角色/模型/推理强度、独立的全新 reviewer、按条件触发的 Judge，以及创建 PR 前的 reviewer PASS。

Issue 正文、PR 文本、评论和审查意见都被视为不可信的仓库内容。它们不能扩大权限，也不能覆盖用户或仓库策略。

## 运行要求

- 兼容 Agent Skills 的编程代理运行时。
- 能够创建、等待并关闭全新的顶层任务或会话。
- 能够在每个 Issue 任务中创建一个持续 worker 和每轮全新的只读 reviewer。
- Git，以及已认证的 GitHub 集成或 `gh` CLI。
- Python 3.10 或更高版本，用于运行生命周期状态脚本。
- 创建分支和 PR 的权限；仅在用户明确授权时才需要合并权限。
- 目标仓库具有可识别的默认分支，以及自己的测试或验证命令。

## 安装

克隆仓库：

```shell
git clone https://github.com/ferryhe/issue-to-merge.git
```

然后按照你的代理运行时所支持的方式注册这个目录。仓库根目录就是完整的 skill 目录，其中包含 `SKILL.md`、manager prompt 和确定性的生命周期脚本。

## 使用

明确指定 Issue，并明确授权完整的合并生命周期：

```text
使用 issue-to-merge skill，按顺序解决 Issue #123 和 #127，把每个 Issue 都推进到合并并完成清理。
```

对于“我们应该如何处理 #123？”这类仅咨询问题，本 skill 不会启动发布和合并流程。发布、合并、删除和清理权限始终只覆盖用户明确指定的 Issue 和仓库。

## 运行时选择

首次使用时，先展示当前设置、分层 Codex 和自定义配置这三种选择。只有用户
选定后，才把完整选择写入安装目录和目标仓库之外；后续运行复用该选择：

```shell
python scripts/runtime_config.py options
python scripts/runtime_config.py preview-current --runtime codex --capabilities /external/current-capabilities.json
python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy current --capabilities /external/current-capabilities.json
python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy tiered
python scripts/runtime_config.py preflight --selection /external/runtime-selection.json --capabilities /external/host-capabilities.json --output /external/issue-123.runtime.json
```

“当前设置”预览使用实际检查到的有效路由，而且不会写文件。保存的选择仍保留
null 继承；每个 Issue 的预检都会重新检查，并冻结具体路由、子代理上限和 Fast
状态。分层 Codex 会明确展示
Sol/Luna/Terra/Astra 的角色路由、最多四个子代理和关闭 Fast；自定义配置保留
客户自己提供的并发和 Fast 选择。脚本只核验调用方提供的主机证据，不声称自动
识别能力，也不会修改 Codex 或 Hermes 的全局配置。详见
[运行时选择约定](references/runtime-selection.md)和
[Codex 适配说明](references/codex-runtime.md)。

自定义策略只能选择完整的严格 assessment/Judge/PASS 生命周期，或现有非严格
生命周期；非严格模式不能混入仅由严格模式执行的策略字段。

原有 `config/models.json` 继续保留，并提供显式迁移；其中的自定义字符串和
null 继承语义不会被预设静默覆盖。

## 状态脚本

Issue manager 会记录交付阶段，controller 会记录最终任务关闭；这些生命周期跳转都写入目标 checkout 之外的 JSON 状态文件：

```shell
python scripts/review_cycle.py --help
python scripts/review_cycle.py status --state-file /path/to/issue-123.state.json
```

该脚本会记录所选运行时快照；选择严格策略时，还会强制执行评估、Judge 和
PASS 门禁。同时继续执行审查轮数上限、准确的 Issue 关闭引用、单次远程反馈
抓取、当前 PR HEAD 的 checks 证据、清理顺序和最终任务关闭证明。没有运行时
快照的旧状态保留原有兼容策略。

## 运行时兼容性

Hermes 每个 Issue 使用独立的 orchestrator manager（`max_spawn_depth >= 2`）。主对话管理队列并核实完成状态；详细证据保存在外部文件，manager 返回结果目标不超过 2,000 字符。参见[上下文约定](references/context-management.md)。修改委派设置后，需核实实际配置并开启新会话。

本项目不规定具体的工具名称。请把每个 Issue 映射为一个全新的可关闭顶层任务或会话，并让其根代理担任 manager；再把持续存在的 implementation worker 和一次性的 local reviewer 映射到运行时的子代理机制。Controller 等待任务完成、核验结果、关闭任务并确认资源释放后，才能创建下一个 Issue 任务。运行时必须保持角色隔离、向每个代理提供所需上下文，并执行 `SKILL.md` 中定义的写入权限边界。在 Hermes Agent 上运行时，请参见 [references/hermes-runtime.md](references/hermes-runtime.md) 了解通用 Hermes 约束，并参见 [references/hermes-profiles-kanban.md](references/hermes-profiles-kanban.md) 了解 Hermes Profiles/Kanban 适配方式，其中包含 profile 与 `config/models.json` 的优先级以及 worker 连续性约束。

## 设计边界

这是一个刻意严格的 Issue 交付工作流，不是通用的自治循环，也不是 GitHub Issue 分类机器人。只有在用户指定具体 Issue 并授权端到端交付后才会启动。人工审查与仓库分支保护始终具有最终决定权。

## 许可证

MIT
