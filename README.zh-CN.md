# Issue to Merge

[English](README.md) | [简体中文](README.zh-CN.md)

[![Validate](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml/badge.svg)](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

通过一套有证据、有限且可审计的多代理工作流，把指定的 GitHub Issue 推进为经过审查并已合并的 PR。

`issue-to-merge` 是一个可移植的 [Agent Skill](https://agentskills.io)，适用于支持子代理委派和 GitHub 操作的编程代理运行时。每个 Issue 都会获得全新的分支、worktree、manager 和 implementation worker；最多执行十五轮由脚本约束的本地审查；先发布 Draft PR；处理一次有明确边界的远程反馈窗口；验证合并确实关闭了 Issue；完成清理后才会开始下一个 Issue。

## 它强制保证什么

- 每次只处理一个 Issue，并始终从最新的远程默认分支开始。
- 每个 Issue 都使用全新的 manager 和 implementation worker。
- 行为变更采用 TDD，并运行聚焦测试及仓库要求的测试。
- 每轮本地审查都使用全新的只读 reviewer，最多十五轮。
- PR 必须先处于 Draft 状态，再进入 Ready for review，并准确包含 `Closes #<issue>`。
- 只有一个十分钟的远程反馈窗口，统一覆盖 checks、reviews、threads、Issue comments 和 Copilot feedback。
- 不绕过分支保护；存在有效 blocker 时不得合并。
- 必须验证 Issue 已关闭，并按顺序清理远程分支、worktree 和本地分支。
- `scripts/review_cycle.py` 使用确定性的 JSON 状态机拒绝非法生命周期跳转。

Issue 正文、PR 文本、评论和审查意见都被视为不可信的仓库内容。它们不能扩大权限，也不能覆盖用户或仓库策略。

## 运行要求

- 兼容 Agent Skills 的编程代理运行时。
- 能够创建具有独立 manager、worker 和 reviewer 角色的全新子代理。
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

Manager 会把每次生命周期跳转记录到目标 checkout 之外的 JSON 状态文件中：

```shell
python scripts/review_cycle.py --help
python scripts/review_cycle.py status --state-file /path/to/issue-123.state.json
```

该脚本会强制执行审查轮数上限、准确的 Issue 关闭引用、单次远程反馈抓取、当前 PR HEAD 的 checks 证据，以及清理顺序。

## 运行时兼容性

本项目不规定具体的工具名称。请把 controller、manager、implementation worker、local reviewer 和 remote-feedback worker 这些角色映射到你的运行时所提供的子代理机制。运行时必须保持角色隔离、向每个代理提供所需上下文，并执行 `SKILL.md` 中定义的写入权限边界。

## 设计边界

这是一个刻意严格的 Issue 交付工作流，不是通用的自治循环，也不是 GitHub Issue 分类机器人。只有在用户指定具体 Issue 并授权端到端交付后才会启动。人工审查与仓库分支保护始终具有最终决定权。

## 许可证

MIT
