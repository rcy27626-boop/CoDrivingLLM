# CoDrivingLLM 文件归类地图

更新时间：2026-09-08  
目的：区分原项目文件、用户自建文件、Codex 生成文件和运行时产物，避免误移动、误删除或误提交。

## 1. 根目录原项目文件：不要移动

这些文件属于原始仓库或已被 Git 跟踪，保留在项目根目录：

- `.env.example`
- `.gitattributes`
- `.gitignore`
- `README.md`
- `requirements.txt`
- `Run_multi_CAV_LLM.py`
- `run_server.sh`
- `run_windows.bat`
- `run_experiment.bat`
- `highway_env/`
- `llm_controller/`
- `videos&data/`

说明：

- `run_server.sh`、`run_windows.bat`、`run_experiment.bat` 虽然是原项目入口脚本，但已经改为读取 `my_workspace/env/` 下的私有配置。
- 不建议把 `requirements.txt`、`Run_multi_CAV_LLM.py`、`highway_env/`、`llm_controller/` 移动到子目录，否则会破坏原项目的导入路径和复现命令。

## 2. 用户自建文件：统一放在 `my_workspace/`

当前结构：

```text
my_workspace/
├─ README.md
├─ env/
│  ├─ .env.server
│  └─ .env.windows
└─ scripts/
   ├─ run_server_batch.sh
   └─ summarize_results.py
```

归类规则：

- 本机/服务器私有环境配置：`my_workspace/env/`
- 用户自己编写的批处理脚本、汇总脚本：`my_workspace/scripts/`
- 后续用户自己产生的实验日志、临时记录：建议使用 `my_workspace/logs/`
- 后续用户自己保存的实验输出：建议使用 `my_workspace/results/<batch>/`

注意：

- `.env.server` 和 `.env.windows` 不入库。
- 根目录 `.env` 是启动脚本复制生成的运行时文件，代码会直接读取它，因此保留在根目录。

## 3. Codex 生成文件：统一放在 `codex_workspace/`

当前结构：

```text
codex_workspace/
├─ AGENTS.md
├─ README.md
├─ task_plan.md
├─ findings.md
├─ progress.md
├─ reports/
└─ change_logs/
```

归类规则：

- 评估报告、研究计划、创新点假设表：`codex_workspace/reports/`
- Codex 工作规则和任务状态：`codex_workspace/` 根目录
- 对 `codex_workspace/` 内文件的创建或修改记录：`codex_workspace/change_logs/`

## 4. 项目源码修改记录：统一放在 `my_modifications/`

当前结构：

```text
my_modifications/
├─ README.md
├─ REPRODUCTION_STEPS.md
└─ change_logs/
```

规则：

- 修改 `Run_multi_CAV_LLM.py`、`llm_controller/`、根目录启动脚本等项目源文件时，必须在 `my_modifications/change_logs/` 添加说明。
- 这些日志用于以后写论文、复现实验和回溯改动。

## 5. 运行时产物：保留原位，不参与归类移动

### `.env`

- 作用：当前生效的环境配置。
- 来源：由 `run_server.sh`、`run_windows.bat` 或 `run_experiment.bat` 从 `my_workspace/env/` 复制生成。
- 是否移动：不移动，因为运行代码直接读取根目录 `.env`。
- 是否提交：不提交，已被 `.gitignore` 忽略。

### `db/`

- 作用：Chroma 向量记忆数据库。
- 当前默认路径：`./db/<env_id>`，由 `llm_controller/memory.py` 决定。
- 是否移动：暂不移动，除非后续显式设置 `MEMORY_DB_DIR` 并同步修改实验脚本。
- 是否提交：不提交，已被 `.gitignore` 忽略。

### `__pycache__/`

- 作用：Python 编译缓存。
- 是否移动：不移动，后续运行会自动重新生成。
- 是否提交：不提交，已被 `.gitignore` 忽略。

## 6. 当前根目录简化后的状态

根目录现在主要包含：

1. 原项目入口和源码；
2. 运行时必需的 `.env`、`db/`、`__pycache__/`；
3. 三个归类工作区：
   - `my_workspace/`
   - `codex_workspace/`
   - `my_modifications/`

因此，不需要再把 `requirements.txt` 这类原项目文件移动进子目录。

## 7. 后续新增文件建议

| 文件类型 | 建议位置 | 是否入库 |
|---|---|---|
| 私有环境配置 | `my_workspace/env/` | 否 |
| 用户批处理脚本 | `my_workspace/scripts/` | 可入库，视个人需求 |
| 用户实验日志 | `my_workspace/logs/<batch>/` | 可选择 |
| 用户实验原始输出 | `my_workspace/results/<batch>/` | 视大小决定 |
| Codex 报告 | `codex_workspace/reports/` | 可入库 |
| Codex 变更日志 | `codex_workspace/change_logs/` | 可入库 |
| 项目源码修改日志 | `my_modifications/change_logs/` | 建议入库 |
| 向量数据库 | `db/` | 否 |
| API Key 配置 | `.env`、`.env.server`、`.env.windows` | 否 |
