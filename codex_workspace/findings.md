# 关键发现

## 已知信息
- 项目：CoDrivingLLM
- 论文：Towards Interactive and Learnable Cooperative Driving Automation: a Large Language Model-Driven Decision-making Framework
- 发表：IEEE Transactions on Vehicular Technology, 2025
- 代码包含：highway_env 仿真层、llm_controller 决策层、记忆库、协商模块、实验运行器
- 仓库已支持：参数化实验、断点续跑、成功/超时/碰撞统计、固定 seed、记忆/协商开关
- 仓库未包含：对比算法完整实现（iDFST、Cooperative Game、MADQN）

## 初步判断
- 作为 baseline：适合，尤其适合“LLM + 协同驾驶决策”方向
- 主要优势：模块化清晰、已有实验基础设施、论文已发表、场景覆盖较完整
- 主要风险：LLM 输出不稳定、记忆库效果待验证、对比算法缺失、实验结果对 prompt/模型版本敏感
- 创新空间：较大，适合从安全过滤、事件触发、自适应记忆、机制设计、不确定性感知等方向切入

## 实验矩阵与复现现状
- 服务器批量脚本已定义三阶段实验矩阵：
  - Part 1：intersection/0shot 30轮、merge/0shot 20轮，且开启 memory-update 建库
  - Part 2：intersection 的 no-negotiation / 2shot / 5shot 各 30轮
  - Part 3：merge 的 no-negotiation / 2shot / 5shot 各 20轮
- 批量脚本支持：
  - `--smoke` 每格 2 轮
  - `--no-video` 加速
  - 断点续跑
  - 按场景/方法过滤
  - 自动汇总 `summarize_results.py`
- 结果统计脚本已内置作者参考成功率：
  - intersection：0shot 74%，2shot 90%，5shot 80%，no-negotiation 15%
  - merge：0shot 75%，2shot 85%，5shot 84%，no-negotiation 33%

## 跨学科创新判断
- 安全过滤层：控制论 / 规则与学习混合系统，最易实现且最可能带来直接收益
- 事件触发决策：控制系统 / 通信效率，可显著降低 LLM 调用次数
- 自适应记忆：认知科学 / 经验学习，可基于现有 Chroma 记忆库改造
- 机制设计协商：博弈论 / 社会选择，理论叙事强但实现复杂度较高
- 不确定性感知：统计决策 / conformal prediction，理论漂亮但实现与解释成本较高
