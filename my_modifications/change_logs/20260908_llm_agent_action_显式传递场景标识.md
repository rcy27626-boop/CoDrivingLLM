# 2026-09-08 决策 prompt 显式传递 intersection 场景标识

## 修改时间
2026-09-08

## 原文件路径
- `F:\study\ky\CoDrivingLLM\llm_controller\llm_agent_action.py`

## 修改目的
修复 `prompt_engineer()` 调用 `available_action()` 时未传递 `is_intersection` 的问题，避免 intersection / merge 场景错误生成换道动作。

## 具体改动
- 将：
  ```python
  msg0 = available_action(self.toolModels, ego_veh, road, env)
  ```
  改为：
  ```python
  msg0 = available_action(self.toolModels, ego_veh, road, env, is_intersection=self.is_intersection)
  ```

## 影响范围
- intersection / merge 场景的可用动作列表只会包含 `IDLE / FASTER / SLOWER`。
- highway 场景仍可包含换道动作。
- 已通过三个场景的无 LLM prompt 生成测试和 intersection 5-step mock 冒烟测试。