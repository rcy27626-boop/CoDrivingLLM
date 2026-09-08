# my_workspace

这个目录用于存放用户自己创建、但不属于原项目自带的文件，便于和原始项目文件区分。

## 目录结构
- `env/`：本机/服务器私有环境配置
  - `.env.server`
  - `.env.windows`
- `scripts/`：用户自己编写的实验脚本
  - `run_server_batch.sh`
  - `summarize_results.py`

## 说明
- `.env` 仍保留在项目根目录，因为运行时代码直接读取它；
- `.env.server` 和 `.env.windows` 是源配置，启动脚本会把它们复制成根目录的 `.env`；
- 以后如果你再创建自己的环境文件、批处理脚本、汇总脚本，建议也放在这个目录下。
