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
- 面向用户的进度和结果使用与用户一致的语言以及简短大白话；完整证据保留在内部报告中。
- 不绕过分支保护；存在有效 blocker 时不得合并。
- 必须验证 Issue 已关闭，并按顺序清理远程分支、worktree 和本地分支。
- 必须验证当前 Issue 任务已经关闭，之后才能开始下一个 Issue。
- `scripts/review_cycle.py` 使用确定性的 JSON 状态机拒绝非法生命周期跳转。
- 通过 `config/models.json` 这一处入口为各角色指定模型；未配置的角色回退到 agent 自身当前模型（交叉模型只是可选，不强制）。

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

## 状态脚本

Issue manager 会记录交付阶段，controller 会记录最终任务关闭；这些生命周期跳转都写入目标 checkout 之外的 JSON 状态文件：

```shell
python scripts/review_cycle.py --help
python scripts/review_cycle.py status --state-file /path/to/issue-123.state.json
```

该脚本会强制执行审查轮数上限、准确的 Issue 关闭引用、单次远程反馈抓取、当前 PR HEAD 的 checks 证据、清理顺序，以及最终的 Issue 任务关闭证明。

## 运行时兼容性

本项目不规定具体的工具名称。请把每个 Issue 映射为一个全新的可关闭顶层任务或会话，并让其根代理担任 manager；再把持续存在的 implementation worker 和一次性的 local reviewer 映射到运行时的子代理机制。Controller 等待任务完成、核验结果、关闭任务并确认资源释放后，才能创建下一个 Issue 任务。运行时必须保持角色隔离、向每个代理提供所需上下文，并执行 `SKILL.md` 中定义的写入权限边界。

## 设计边界

这是一个刻意严格的 Issue 交付工作流，不是通用的自治循环，也不是 GitHub Issue 分类机器人。只有在用户指定具体 Issue 并授权端到端交付后才会启动。人工审查与仓库分支保护始终具有最终决定权。

## 许可证

MIT
