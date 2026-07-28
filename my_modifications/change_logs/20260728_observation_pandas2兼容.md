# 20260728 - pandas 2.x 兼容：`_append` / `append` → `pd.concat`

## 📅 修改时间
2026-07-28

## 📂 修改的原项目文件
- `highway_env/envs/common/observation.py`

## 🎯 修改目的

服务器上实际环境是 **pandas 1.3.5 + numpy 1.26.4**，而 pandas 1.3.5（2021）依赖 numpy 1.17~1.23 的 API，与 numpy 1.26.4（2023）不兼容，导致 `df._append()` 内部加载失败，报：

```
AttributeError: 'DataFrame' object has no attribute '_append'
```

requirements.txt 写的是 `pandas==1.3.5`，但环境里 numpy 已经是 1.26.4，强行保留旧 pandas 会出现这种诡异报错。

**解决思路：升级 pandas 到 2.x，同时把代码中已 deprecated 的私有 API 换成公共 API `pd.concat`。**

## 🔧 具体改动

### 改动 1：[observation.py:208-211](highway_env/envs/common/observation.py#L208-L211)

**原代码（用私有方法 `_append`）：**
```python
df = df._append(pd.DataFrame.from_records(
    [v.to_dict(origin, observe_intentions=self.observe_intentions)
     for v in close_vehicles[-self.vehicles_count + 1:]])[self.features],
                ignore_index=True)
```

**改成（用 `pd.concat`，pandas 2.x 推荐写法）：**
```python
df = pd.concat([df, pd.DataFrame.from_records(
    [v.to_dict(origin, observe_intentions=self.observe_intentions)
     for v in close_vehicles[-self.vehicles_count + 1:]])[self.features]],
               ], ignore_index=True)
```

### 改动 2：[observation.py:219](highway_env/envs/common/observation.py#L219)

**原代码（用 `df.append`，2.0 deprecated）：**
```python
df = df.append(pd.DataFrame(data=rows, columns=self.features), ignore_index=True)
```

**改成（用 `pd.concat`）：**
```python
df = pd.concat([df, pd.DataFrame(data=rows, columns=self.features)], ignore_index=True)
```

## ⚠️ 影响范围

| 模块 | 影响 |
|------|------|
| `intersection-multi-agent-v0` | ✅ 是（默认跑这个场景） |
| `highway-v0` | ✅ 是（也用 observation 模块） |
| `merge-multi-agent-v0` | ✅ 是 |
| LLM 决策模块 | ❌ 不影响（observation.py 只在 gym 环境初始化和 step 时调用） |

## 📌 服务器端配套操作

```bash
# 1. 拉取最新代码
cd /media/ubuntu/Student/rcy/CoDrivingLLM
git pull

# 2. 升级 pandas 到 2.x（解决与 numpy 1.26.4 的版本错配）
pip install "pandas>=2.0"

# 3. 验证
python -c "import pandas; print(pandas.__version__)"   # 应 >= 2.0

# 4. 重跑冒烟测试
conda activate codrivingllm
python Run_multi_CAV_LLM.py
```

## 🔍 经验总结

📚 **requirements.txt 写得太老是个坑**：
- `pandas==1.3.5` 强制锁死，导致 pip 解析时强制使用旧版本，与 conda 自带的新 numpy 冲突
- 实际复现中，遇到老仓库 + 新环境，最稳妥的做法是：
  1. 不严格锁版本（去掉 `==`）
  2. 或者同步升级 numpy + pandas
  3. 或者改代码用最新公共 API（本次做法）

## 🔄 后续建议（可选）

- [ ] 把 `requirements.txt` 里的 `pandas==1.3.5` 改成 `pandas>=2.0`
- [ ] 全仓库再扫一遍是否有其他 deprecated API
- [ ] 跑通后记录到 `REPRODUCTION_STEPS.md` 的"已知风险点"里
