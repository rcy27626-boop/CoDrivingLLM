# 20260910 load_dotenv(override=True)：修复 shell 残留环境变量覆盖 .env 导致 embedding 401

## 一、问题现象
- 服务器冒烟实验（--memory-update 建库）每一步都报：
  `Failed to add scenario: Error code: 401 - {'code': 30014, 'data': None, 'message': 'Token is invalid.'}`
- 记忆库始终 `0 items`，建库完全失败；但用 `.env` 里的 key 直接 curl SiliconFlow embeddings 返回 **HTTP 200**。
- 对比发现两把不同的 key（均 51 位）：
  - shell 环境变量：`SILICONFLOW_API_KEY=sk-jgd...`（旧/无效）
  - `.env` 文件：`SILICONFLOW_API_KEY=sk-rcx...`（有效）

## 二、根因
- `memory.py` / `llm_agent_action.py` / `llm_agent_negotiation_system.py` 均调用 `load_dotenv()`。
- python-dotenv 默认 `override=False`：**若环境中已存在同名变量，则保留环境变量值、不采用 .env 值**。
- 服务器 shell 中残留旧 key（`sk-jgd...`），导致 memory.py 顶层 `os.getenv("SILICONFLOW_API_KEY")` 读到旧 key，embedding 调用 401。
- 每开新终端旧 key 仍在 → 说明该变量可能被 `.bashrc` / conda 环境持久化设置，`unset` 只对当前会话有效。

## 三、修改内容
统一将三处 `load_dotenv()` 改为 `load_dotenv(override=True)`，让 `.env` 成为唯一权威配置，强制覆盖 shell 残留变量：
1. `llm_controller/memory.py` 第 10 行
2. `llm_controller/llm_agent_action.py` 第 12 行
3. `llm_controller/llm_agent_negotiation_system.py` 第 11 行

## 四、验证
- `python -m py_compile llm_controller/memory.py llm_controller/llm_agent_action.py llm_controller/llm_agent_negotiation_system.py` 通过。

## 五、服务器验证命令
```bash
git pull origin master
# 重跑冒烟（新进程才会生效，单例客户端会缓存 key）
rm -rf llm_controller/result/20260909_smoke4
bash my_workspace/scripts/run_server_batch.sh --smoke --scene intersection --methods 0shot --batch 20260910_smoke5 --no-video
```
期望：不再出现 `Failed to add scenario: 401`，记忆库 items 随步数增长。

## 六、附加排查建议（定位旧 key 来源）
```bash
grep -rn "SILICONFLOW" ~/.bashrc ~/.bash_profile ~/.profile ~/.bash_aliases /etc/profile.d/ 2>/dev/null
grep -rn "SILICONFLOW" "$CONDA_PREFIX/etc/conda/" 2>/dev/null
```
