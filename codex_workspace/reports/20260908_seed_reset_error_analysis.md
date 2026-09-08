# 旧版 Gym / Highway-env 随机种子报错分析与修复记录

日期：2026-09-08  
对象：`Run_multi_CAV_LLM.py` 的每轮 `env.reset()` 与随机种子设置逻辑

## 1. 三轮报错的时间线

### 第一轮：新版 API 语法用到了旧版环境

报错：

```text
TypeError: reset() got an unexpected keyword argument 'seed'
```

当时代码：

```python
obs = env.reset(seed=args.seed + i)
```

原因：

- `requirements.txt` 固定为 `gym==0.15.3`；
- 本仓库自带的 `highway_env` 基类签名为：

```python
def reset(self, is_training=True, testing_seeds=0):
```

- 因此它不支持新版 Gymnasium 的 `reset(seed=...)` 写法。

结论：  
这不是 seed 数值问题，而是 API 版本不匹配。

### 第二轮：错误地调用了 `env.seed()`

第一次修复尝试：

```python
try:
    obs = env.reset(seed=args.seed + i)
except TypeError:
    env.seed(args.seed + i)
    obs = env.reset()
```

报错：

```text
TypeError: 'int' object is not callable
```

原因在 `highway_env/envs/common/abstract.py`：

```python
def __init__(self, config=None):
    self.seed = self.config["seed"]  # 实例属性，整数

def seed(self, seeding=None):
    seed = np.random.seed(self.seed)
    return [seed]
```

Python 中，实例属性会遮蔽同名类方法。  
因此运行时：

```python
env.seed
```

得到的是整数属性，而不是方法。

调用：

```python
env.seed(42)
```

等价于：

```python
42(42)
```

所以报：

```text
'int' object is not callable
```

结论：  
不能调用这个旧版环境对象的 `env.seed()`。

### 第三轮：手工插入 NumPy seed 时破坏缩进

第二次修复尝试：

```python
np.random.seed(args.seed + i)
try:
    obs = env.reset(seed=args.seed + i)
except TypeError:
    obs = env.reset()
```

报错：

```text
IndentationError: unexpected indent
```

原因：

- `import numpy as np` 被插入到循环内部；
- `np.random.seed(...)` 的缩进层级与 `try` 不一致；
- Python 对控制流缩进敏感，导致语法错误。

结论：  
第三个错误是热修复过程中的编辑失误，不是环境本身的新问题。

## 2. 之前方案为什么没有成功

| 尝试 | 结果 | 原因 |
|---|---|---|
| `env.reset(seed=...)` | 失败 | 旧版环境不支持 `seed` 参数 |
| `env.seed(...)` | 失败 | `seed` 被整数实例属性遮蔽，不是方法 |
| 手动 `np.random.seed(...)` | 语法失败 | 插入位置和缩进错误 |
| 仅设置 NumPy 全局种子 | 即使语法正确也不够严谨 | 环境内部同时使用 `numpy.random` 和 `random`，只固定一个随机源不完整 |

## 3. 最终正确修复

修改 `Run_multi_CAV_LLM.py`：

```python
obs = env.reset(is_training=False, testing_seeds=args.seed + i)
```

### 为什么这是正确接口

本仓库 `highway_env/envs/common/abstract.py` 的 reset 实现为：

```python
def reset(self, is_training=True, testing_seeds=0):
    if is_training:
        np.random.seed(self.seed)
        random.seed(self.seed)
    else:
        np.random.seed(testing_seeds)
        random.seed(testing_seeds)
```

当使用：

```python
is_training=False
testing_seeds=args.seed + i
```

时，环境内部会同时设置：

```python
np.random.seed(args.seed + i)
random.seed(args.seed + i)
```

因此它比手动只设置 NumPy 种子更完整。

## 4. 验证结果

对三个实验场景分别执行相同 seed 的两次 reset：

```python
o1 = env.reset(is_training=False, testing_seeds=42)
o2 = env.reset(is_training=False, testing_seeds=42)
```

验证结果：

```text
intersection-multi-agent-v0 same_obs=True
merge-multi-agent-v0 same_obs=True
highway-v0 same_obs=True
```

同时检查：

```bash
python -m py_compile Run_multi_CAV_LLM.py
```

通过。

## 5. 对实验公平性的影响

修复后，第 `i` 轮使用：

```text
seed = args.seed + i
```

相同场景、相同轮次、不同方法会得到相同初始 observation。  
这满足 baseline 对比实验的基本公平性要求。

## 6. 服务器同步建议

当前修复已经写入本地 `Run_multi_CAV_LLM.py`。  
在你确认后提交代码，然后在服务器上同步。

如果服务器上有手工修改过且未提交的文件，建议先备份：

```bash
cp Run_multi_CAV_LLM.py Run_multi_CAV_LLM.py.bak
```

再拉取最新代码：

```bash
git pull origin master
```

最后重新执行冒烟测试。

## 7. 结论

三轮错误的根本链条是：

1. 先按新版 Gymnasium API 使用了 `reset(seed=...)`；
2. 然后按常见 gym 习惯调用了 `env.seed()`，但该仓库的实例属性遮蔽了同名方法；
3. 最后手工热修复时破坏了缩进。

最终修复不使用猜测式兼容层，而是直接采用本仓库旧版 `highway_env` 明确支持的：

```python
reset(is_training=False, testing_seeds=...)
```
