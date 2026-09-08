# Codex 工作区

这个目录专门存放 Codex 创建或管理的文件，避免与项目原始文件混淆。

## 目录结构
- `AGENTS.md`：Codex 工作规则与记忆
- `task_plan.md`：当前任务计划
- `findings.md`：关键发现
- `progress.md`：进度日志
- `reports/`：报告、评估、方案等正式文档
- `change_logs/`：对 `codex_workspace/` 内文件的修改记录

## 使用原则
- 新建文件优先放在本目录；
- 修改项目源文件时，在 `my_modifications/change_logs/` 中记录；
- 修改或新建 `codex_workspace/` 内文件时，在 `codex_workspace/change_logs/` 中记录；
- 不要把临时文件散落到项目其他目录。
