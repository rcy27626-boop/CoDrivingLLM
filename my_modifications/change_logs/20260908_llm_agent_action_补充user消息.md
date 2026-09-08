# 2026-09-08 决策 LLM 请求补充 user 消息

## 修改时间
2026-09-08

## 原文件路径
- `F:\study\ky\CoDrivingLLM\llm_controller\llm_agent_action.py`

## 修改目的
修复 `qwen3.8:27b` 在决策阶段可能出现的同类错误：

```text
no user query found in messages
```

## 具体改动
- 将原来只包含 `system` 消息的请求改为 `system + user` 双消息格式。
- 原完整驾驶决策任务提示放入 `user` 消息。
- `system` 消息只保留角色和输出格式约束。

## 影响范围
- 修复决策模块对新版 Qwen 模型的兼容性。
- 不改变 prompt 生成、动作解析和动作映射逻辑。
- 已用假 OpenAI 客户端验证请求 roles 为 `['system', 'user']`，且 user 内容非空。