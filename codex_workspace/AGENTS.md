# Codex 工作区记忆

## 规则
1. 以后所有由 Codex 创建的新文件，默认放在 `codex_workspace/` 目录内。
2. 如果用户明确要求创建或整理“用户自己的工作文件”，可使用 `my_workspace/`：
   - 环境配置放在 `my_workspace/env/`
   - 用户自写脚本放在 `my_workspace/scripts/`
3. 如果修改项目原有源文件，例如 `Run_multi_CAV_LLM.py`、`memory.py`、`run_server_batch.sh`，必须同时在：
   - `F:\study\ky\CoDrivingLLM\my_modifications\change_logs\`
   
   中添加一条修改说明，格式为：
   - `YYYYMMDD_<原文件名>_<简短描述>.md`
   - 内容包含：修改时间、原文件路径、修改目的、具体改动、影响范围。

4. 如果创建了新文件，或者修改了 `codex_workspace/` 中的任何文件，必须同时在：
   - `F:\study\ky\CoDrivingLLM\codex_workspace\change_logs\`
   
   中添加一条修改说明，格式为：
   - `YYYYMMDD_<文件名>_<简短描述>.md`
   - 内容包含：修改时间、文件路径、修改目的、具体改动、影响范围。

5. 不要把 Codex 生成的报告、计划、临时文件散落在项目根目录或其他业务目录中。
6. 如果确实必须在项目根目录创建配置类文件，需先在 `codex_workspace/change_logs/` 中说明原因。
7. 每次重要阶段结束后，更新 `codex_workspace/progress.md`。
