# 2026-09-08 修复加速安全工具 inference 参数不匹配

## 修改时间
2026-09-08

## 原文件路径
- `F:\study\ky\CoDrivingLLM\llm_controller\prompt_llm.py`

## 修改目的
修复服务器冒烟测试中的崩溃：

```text
TypeError: inference() missing 1 required positional argument: 'env'
```

## 具体改动
- `isAccelerationConflictWithCar.inference()` 的签名从 `(self, vid, ego_veh, env)` 改为 `(self, vid, ego_veh)`。
- 原因：该函数内部没有使用 `env`，而 `check_safety_in_current_lane()` 中的调用只传入 `(vid, ego_veh)`；移除未使用参数可与其他同车道安全工具保持一致。

## 影响范围
- 修复 `prompt_engineer()` -> `check_safety_in_current_lane()` -> 加速安全判断链路。
- 不改变加速安全判断的计算逻辑，只修复接口不匹配。
- 已通过 intersection / merge / highway 三个场景的无 LLM prompt 生成测试。