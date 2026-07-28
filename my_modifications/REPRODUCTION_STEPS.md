# CoDrivingLLM 复现步骤

> 配合 `my_modifications/README.md` 的工作流使用：
> 本机改 → `git push` → 服务器 `git pull` → 跑实验

---

## ✅ 已完成（用户当前状态）

- [x] 项目文件已从 GitHub 拉到 Linux 服务器
- [x] 已按 `requirements.txt` 配置好 conda 环境

---

## 📋 待办步骤

### 🔧 步骤 1：配置 API Key 与代理

**位置**：`llm_controller/llm_agent_negotiation_system.py:8`
```python
api_key = "your key here"   # ← 替换成真实 key
```

**代理配置**（第 143-145 行）：
```python
proxy_url = "http://127.0.0.1:7890"
```
- 如果服务器**不挂 VPN**，删掉这三行
- 如果服务器**有 VPN**，改成对应代理地址
- 或者统一用环境变量（推荐，避免硬编码泄露 key 到 git）

> 💡 改进建议：把 API Key 改成环境变量读取，修改后记录到 `change_logs/`

---

### 🧪 步骤 2：先小规模冒烟测试

**修改**：`Run_multi_CAV_LLM.py:58`
```python
for i in range(100):      # 原代码
for i in range(2):        # 改：先跑 2 轮
```

**服务器上执行：**
```bash
cd CoDrivingLLM
python Run_multi_CAV_LLM.py
```

**观察：**
- 是否能正常 `gym.make('intersection-multi-agent-v0')`
- 是否能成功调用 OpenAI API
- 视频是否生成到 `llm_controller/video/0.mp4`、`1.mp4`
- excel 是否生成到 `llm_controller/excel/0.xlsx`、`1.xlsx`
- 控制台是否打印出 `llm_actions` 和 `global_reward`

**预期可能报错：**
- `gym` / `highway-env` 版本不兼容（依赖太旧）
- `openai.APIError`（key 无效 / 余额不足 / 网络不通）
- `chromadb` 初始化失败

---

### 🚀 步骤 3：全量跑 100 轮

冒烟测试通过后，把 `range(2)` 改回 `range(100)`，推到服务器跑全量：
```bash
python Run_multi_CAV_LLM.py
```

> ⚠️ **成本提醒**：每轮会多次调用 `gpt-4o-mini`，100 轮 token 消耗较大，注意 OpenAI 余额。

---

### 🔄 步骤 4：切换其他场景

在 `Run_multi_CAV_LLM.py:54-55` 切换场景：
```python
env = gym.make('intersection-multi-agent-v0')  # 默认：十字路口
# env = gym.make('highway-v0')                 # 高速场景
# env = gym.make('merge-multi-agent-v0', config={...})  # 合流场景
```

每个场景分别跑 100 轮，生成对应的视频+数据。

---

### 📊 步骤 5：结果整理

实验数据已经自动保存到：
- `llm_controller/video/<i>.mp4`   视频
- `llm_controller/excel/<i>.xlsx`  每辆车每个时刻的 (t, x, y, v, theta, background_veh?)

可以基于这些数据：
1. 提取轨迹、速度曲线
2. 与 `videos&data/` 中作者提供的结果做对比
3. 与作者对比算法（iDFST, Cooperative Game, MADQN）对照分析

---

## ⚠️ 已知风险点

| 风险 | 说明 | 应对 |
|------|------|------|
| 🐍 依赖太旧 | `gym==0.15.3`、`langchain==0.0.335`、`chromadb==0.4.15` | pip install 时若失败，可放宽版本号试装 |
| 🖼️ 服务器无 GUI | `pygame` 渲染 | 已用 `env.render('rgb_array')` 存视频，应该没问题 |
| 💸 API 费用 | 100轮 × 多次 LLM 调用 | 冒烟测试 → 全量 |
| 🔐 Key 硬编码 | `api_key = "your key here"` 在 git 里 | 改用环境变量，避免泄露 |
| 🌐 代理不可用 | `http://127.0.0.1:7890` 是本机代理 | 服务器上视情况删改 |

---

## 🗂️ 推荐的改进工作（可选）

1. **API Key 改造**（建议先做）
   - 文件：`llm_controller/llm_agent_negotiation_system.py`、`llm_controller/llm_agent_action.py`
   - 改成 `api_key = os.getenv("OPENAI_API_KEY")`
   - 服务器上 `export OPENAI_API_KEY=sk-xxx`
   - 记录到 `my_modifications/change_logs/`

2. **日志增强**
   - 加 `logging` 替代 `print`
   - 记录每轮的 token 消耗

3. **批处理模式**
   - 避免反复 `git push/pull`
   - 通过参数控制场景和轮数
