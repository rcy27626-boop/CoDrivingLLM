# CoDrivingLLM 科研执行计划

> 生成日期：2026-09-08  
> 目标：复现 CoDrivingLLM，作为 baseline，并在其上提出可验证的跨学科创新点。  
> 适用范围：课题组内部科研规划，不是正式论文评审结论。

---

## 1. 论文相关信息

### 1.1 论文与代码
- 论文：*Towards Interactive and Learnable Cooperative Driving Automation: a Large Language Model-Driven Decision-making Framework*
- 发表：IEEE Transactions on Vehicular Technology, 2025
- 代码仓库：本项目 `F:\study\ky\CoDrivingLLM`
- 论文方向：LLM 驱动的多车协同驾驶决策
- 核心模块：
  1. 自然语言场景描述
  2. 冲突协商
  3. LLM 动作决策
  4. 向量记忆库
  5. highway-env 仿真闭环

### 1.2 仓库当前能力
- 场景：`intersection`、`merge`、`highway`
- 方法：`0shot`、`2shot`、`5shot`、`no-negotiation`
- 已支持：
  - 参数化实验
  - 固定 seed
  - 断点续跑
  - 成功 / 碰撞 / 超时 / 到达统计
  - LLM 调用次数统计
  - 解析失败统计
  - 服务器批量脚本
  - 结果汇总脚本

### 1.3 主要限制
- 仓库未包含论文中全部对比算法实现；
- LLM 输出受模型版本、prompt、温度、网络波动影响；
- 记忆库内容会影响 2-shot / 5-shot 结果；
- 当前批量脚本主要覆盖 `intersection` 和 `merge`，`highway` 需要单独补充。

### 1.4 作者参考成功率
| 场景 | 方法 | 作者参考值 |
|---|---|---:|
| intersection | 0-shot | 74% |
| intersection | 2-shot | 90% |
| intersection | 5-shot | 80% |
| intersection | no-negotiation | 15% |
| merge | 0-shot | 75% |
| merge | 2-shot | 85% |
| merge | 5-shot | 84% |
| merge | no-negotiation | 33% |

> 这些数值仅作为复现趋势参考，不能替代你的实验结果。

---

## 2. 创新点设计

### 2.1 推荐总体创新组合

**核心组合：安全过滤 + 事件触发 + 自适应记忆**

系统逻辑：

```text
低风险 → 少调用 LLM → 复用经验
高风险 → 调用 LLM → 生成候选动作
输出后 → 安全过滤 → 执行安全动作
```

这个组合的优点：
1. 实现难度适中；
2. 每个模块都可以独立消融；
3. 论文可以从控制论、认知科学、系统效率三个角度展开；
4. 实验指标容易量化；
5. 与现有代码结构高度契合。

---

### 2.2 H1：安全过滤层

**假设：**  
在 LLM 输出后加入安全过滤器，可以降低碰撞率，同时不明显降低成功率。

**跨学科来源：**  
控制论、安全工程、混合系统

**拟新增模块：**
- `llm_controller/safety_filter.py`

**拟新增开关：**
- `--safety-filter`

**核心指标：**
- 碰撞率
- 成功率
- 超时率
- 平均速度
- 安全覆盖次数

**判别标准：**
- 支持假设：
  - 碰撞率下降 ≥ 20%
  - 成功率下降 ≤ 5%
  - 超时率上升 ≤ 10%
- 不支持假设：
  - 碰撞率下降不明显
  - 或成功率下降 > 10%
  - 或系统过度保守

---

### 2.3 H2：事件触发 LLM 决策

**假设：**  
采用事件触发机制后，LLM 调用次数下降 ≥ 30%，成功率下降 ≤ 5%。

**跨学科来源：**  
控制系统、通信效率、事件驱动架构

**拟新增模块：**
- `llm_controller/event_trigger.py`

**拟新增开关：**
- `--event-trigger`

**核心指标：**
- LLM 调用次数
- token 消耗
- 成功率
- 碰撞率
- 平均延迟

**判别标准：**
- 支持假设：
  - 调用次数下降 ≥ 30%
  - 成功率下降 ≤ 5%
  - 碰撞率不上升
- 不支持假设：
  - 调用次数下降不明显
  - 或成功率下降 > 10%

---

### 2.4 H3：自适应记忆与遗忘

**假设：**  
基于场景相似度、时间衰减和成功率的自适应记忆检索，优于固定 2-shot / 5-shot。

**跨学科来源：**  
认知科学、经验学习、检索增强生成

**拟修改模块：**
- `llm_controller/memory.py`
- `llm_controller/llm_agent_action.py`

**拟新增开关：**
- `--adaptive-memory`
- `--memory-forgetting`

**核心指标：**
- 成功率
- 碰撞率
- 平均检索条数
- 记忆命中率
- 无效记忆引用率

**判别标准：**
- 支持假设：
  - 成功率高于固定 2-shot / 5-shot
  - 碰撞率不上升
  - 平均检索条数可控
- 不支持假设：
  - 成功率无提升
  - 或记忆检索成本明显上升

---

### 2.5 H4：机制设计式协商

**假设：**  
基于冲突图和优先级机制的协商方法，在成功率、碰撞率和公平性指标上优于原始 LLM 协商。

**跨学科来源：**  
博弈论、社会选择、机制设计

**拟新增模块：**
- `llm_controller/conflict_graph.py`
- 修改 `llm_agent_negotiation_system.py`

**核心指标：**
- 成功率
- 碰撞率
- 平均等待时间
- 公平性指标
- 协商消息长度

**判别标准：**
- 支持假设：
  - 成功率提高
  - 碰撞率下降
  - 平均等待时间下降
  - 车辆间通行分布更均衡
- 不支持假设：
  - 成功率无提升
  - 或协商延迟显著上升

---

### 2.6 H5：不确定性感知决策

**假设：**  
当 LLM 或环境预测不确定性较高时，触发保守动作，可降低分布外场景中的碰撞率。

**跨学科来源：**  
统计决策、conformal prediction、鲁棒控制

**拟新增模块：**
- `llm_controller/uncertainty.py`

**核心指标：**
- 碰撞率
- 成功率
- 高不确定性子集表现
- 保守动作触发率
- 校准误差

**判别标准：**
- 支持假设：
  - 高不确定性场景碰撞率下降
  - 保守动作触发与实际风险相关
  - 整体成功率下降 ≤ 10%
- 不支持假设：
  - 不确定性估计与实际风险无相关
  - 或只是通过过度保守降低碰撞

---

## 3. 当前复现实验设计

### 3.1 当前批量实验矩阵

`run_server_batch.sh` 目前定义了三部分实验。

#### Part 1：建库 + 0-shot
| 场景 | 方法 | 轮次 | 是否建库 |
|---|---|---:|---|
| intersection | 0-shot | 30 | 是 |
| merge | 0-shot | 20 | 是 |

#### Part 2：intersection 消融
| 场景 | 方法 | 轮次 | 是否建库 |
|---|---|---:|---|
| intersection | no-negotiation | 30 | 否 |
| intersection | 2-shot | 30 | 否 |
| intersection | 5-shot | 30 | 否 |

#### Part 3：merge 消融
| 场景 | 方法 | 轮次 | 是否建库 |
|---|---|---:|---|
| merge | no-negotiation | 20 | 否 |
| merge | 2-shot | 20 | 否 |
| merge | 5-shot | 20 | 否 |

> 说明：当前批量脚本未包含 `highway`，后续需要单独补充。

---

### 3.2 冒烟测试命令

建议先跑 2 轮，确认环境、API、记忆库和输出文件都正常。

```bash
./run_server_batch.sh --smoke --batch 20260908_smoke --no-video
```

如果只想测试单个场景：

```bash
./run_server_batch.sh --smoke --scene intersection --batch 20260908_smoke_intersection --no-video
```

如果只想测试单个方法：

```bash
./run_server_batch.sh --smoke --methods 0shot --batch 20260908_smoke_0shot --no-video
```

---

### 3.3 正式复现命令

#### 第一步：建库 + 0-shot

```bash
./run_server_batch.sh --part 1 --batch 20260908_build --no-video
```

#### 第二步：intersection 消融

```bash
./run_server_batch.sh --part 2 --batch 20260908_intersection --no-video
```

#### 第三步：merge 消融

```bash
./run_server_batch.sh --part 3 --batch 20260908_merge --no-video
```

#### 一次性全量运行

```bash
./run_server_batch.sh --batch 20260908_full --no-video
```

> 建议先分阶段跑，确认每部分结果正常后再全量运行。

---

### 3.4 结果汇总命令

以 `20260908_full` 为例：

```bash
python summarize_results.py --batch 20260908_full \
    --output my_modifications/new_files/reports/20260908_full_report.md \
    --csv my_modifications/new_files/reports/20260908_full_summary.csv
```

如果只想汇总 intersection：

```bash
python summarize_results.py --batch 20260908_intersection \
    --output my_modifications/new_files/reports/20260908_intersection_report.md \
    --csv my_modifications/new_files/reports/20260908_intersection_summary.csv
```

---

## 4. 后续实验设计

### 4.1 阶段 0：补充 highway baseline

当前批量脚本未覆盖 highway，需要单独跑。

建议命令：

```bash
python Run_multi_CAV_LLM.py \
    --scene highway \
    --method 0shot \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_highway_baseline \
    --no-video
```

如需 2-shot / 5-shot：

```bash
python Run_multi_CAV_LLM.py \
    --scene highway \
    --method 2shot \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_highway_memory \
    --no-video
```

```bash
python Run_multi_CAV_LLM.py \
    --scene highway \
    --method 5shot \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_highway_memory \
    --no-video
```

---

### 4.2 阶段 1：安全过滤实验

> 需要先实现 `safety_filter.py` 和 `--safety-filter` 开关。

#### intersection 安全过滤

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method 0shot \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_safety_intersection \
    --no-video \
    --safety-filter
```

#### merge 安全过滤

```bash
python Run_multi_CAV_LLM.py \
    --scene merge \
    --method 0shot \
    --n 20 \
    --start 0 \
    --seed 42 \
    --batch 20260908_safety_merge \
    --no-video \
    --safety-filter
```

#### 安全过滤 + 记忆

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method 2shot \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_safety_memory \
    --no-video \
    --safety-filter
```

---

### 4.3 阶段 2：事件触发实验

> 需要先实现 `event_trigger.py` 和 `--event-trigger` 开关。

#### intersection 事件触发

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method 0shot \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_event_intersection \
    --no-video \
    --event-trigger
```

#### merge 事件触发

```bash
python Run_multi_CAV_LLM.py \
    --scene merge \
    --method 0shot \
    --n 20 \
    --start 0 \
    --seed 42 \
    --batch 20260908_event_merge \
    --no-video \
    --event-trigger
```

#### 事件触发 + 安全过滤

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method 0shot \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_event_safety \
    --no-video \
    --event-trigger \
    --safety-filter
```

---

### 4.4 阶段 3：自适应记忆实验

> 需要先改造 `memory.py`，新增自适应检索与遗忘机制。

#### intersection 自适应记忆

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method adaptive \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_adaptive_memory_intersection \
    --no-video \
    --adaptive-memory
```

#### merge 自适应记忆

```bash
python Run_multi_CAV_LLM.py \
    --scene merge \
    --method adaptive \
    --n 20 \
    --start 0 \
    --seed 42 \
    --batch 20260908_adaptive_memory_merge \
    --no-video \
    --adaptive-memory
```

#### 自适应记忆 + 遗忘

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method adaptive \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_adaptive_memory_forgetting \
    --no-video \
    --adaptive-memory \
    --memory-forgetting
```

---

### 4.5 阶段 4：组合创新实验

#### 安全过滤 + 事件触发

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method 0shot \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_combo_safety_event \
    --no-video \
    --safety-filter \
    --event-trigger
```

#### 安全过滤 + 事件触发 + 自适应记忆

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method adaptive \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_combo_full \
    --no-video \
    --safety-filter \
    --event-trigger \
    --adaptive-memory
```

#### merge 泛化验证

```bash
python Run_multi_CAV_LLM.py \
    --scene merge \
    --method adaptive \
    --n 20 \
    --start 0 \
    --seed 42 \
    --batch 20260908_combo_full_merge \
    --no-video \
    --safety-filter \
    --event-trigger \
    --adaptive-memory
```

---

### 4.6 阶段 5：补充对比算法

#### 规则基线：IDM / PIDM

优先实现规则基线，成本低、说服力高。

建议新增：
- `llm_controller/rule_baseline.py`
- `--method idm`
- `--method pidm`

示例命令：

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method idm \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_rule_baseline \
    --no-video
```

#### 学习基线：PPO

如果时间允许，再补一个学习类基线。

建议新增：
- `llm_controller/ppo_baseline.py`
- `--method ppo`

示例命令：

```bash
python Run_multi_CAV_LLM.py \
    --scene intersection \
    --method ppo \
    --n 30 \
    --start 0 \
    --seed 42 \
    --batch 20260908_ppo_baseline \
    --no-video
```

---

## 5. 推荐执行顺序

```text
第 1 步：冒烟测试
第 2 步：正式复现 intersection + merge
第 3 步：补充 highway baseline
第 4 步：实现安全过滤器
第 5 步：实现事件触发
第 6 步：改造自适应记忆
第 7 步：组合创新实验
第 8 步：补充规则基线
第 9 步：补充学习基线（可选）
第 10 步：统一统计分析与画图
```

---

## 6. 统计与写作建议

### 6.1 建议统计指标
- 成功率
- 碰撞率
- 超时率
- 车辆到达率
- 平均速度
- 平均步数
- LLM 调用次数
- token 消耗
- 解析失败率
- 安全覆盖次数
- 事件触发率
- 记忆命中率

### 6.2 建议增加
- 多 seed 重复实验
- 95% 置信区间
- 显著性检验
- 消融实验
- 跨场景泛化实验
- 失败案例分析

### 6.3 论文写作角度
1. 系统架构：LLM + 安全约束 + 事件触发 + 记忆增强
2. 控制论：安全过滤器作为动作级约束控制器
3. 认知科学：自适应记忆与经验学习
4. 交通工程：冲突消解、效率与公平性
5. 系统效率：LLM 调用成本与延迟
6. 统计评估：多 seed、置信区间与消融分析
7. 人机交互：LLM 输出可解释性
8. 安全关键系统：LLM 在自动驾驶决策中的适用边界

---

## 7. 最终推荐路线

**短期目标：**
1. 跑通 `20260908_smoke`
2. 完成 `20260908_build`
3. 完成 `20260908_intersection`
4. 完成 `20260908_merge`

**中期目标：**
1. 实现安全过滤器
2. 实现事件触发
3. 改造自适应记忆
4. 做组合创新实验

**长期目标：**
1. 补充 highway
2. 补充规则基线
3. 补充学习基线
4. 做跨场景泛化与统计显著性分析
5. 形成论文初稿
