# 20260909 run_server_batch.sh 补可执行权限（修复服务器"权限不够"）

## 一、问题现象
- 服务器执行 `./my_workspace/scripts/run_server_batch.sh --smoke ...` 报：
  `-bash: ./my_workspace/scripts/run_server_batch.sh: 权限不够`

## 二、根因
- 脚本在 git 索引中的权限模式为 `100644`（无执行位 `x`）。
- 文件提交/推送后，Linux 服务器 pull 得到的是无执行权限的文件，不能直接 `./` 运行。

## 三、修改内容
1. `my_workspace/scripts/run_server_batch.sh`
   - `git update-index --chmod=+x`：索引权限 100644 → 100755（内容不变）。

## 四、验证
- `git ls-files -s my_workspace/scripts/run_server_batch.sh` → `100755`。

## 五、服务器可用命令
```bash
# 方案1：本次会话直接加执行位后运行
chmod +x my_workspace/scripts/run_server_batch.sh
./my_workspace/scripts/run_server_batch.sh --smoke --scene intersection --methods 0shot --batch 20260909_smoke --no-video

# 方案2：不依赖执行位，直接用 bash 调用
bash my_workspace/scripts/run_server_batch.sh --smoke --scene intersection --methods 0shot --batch 20260909_smoke --no-video

# 方案3：pull 本次修复提交后（索引已是 100755），重新 clone 或 checkout 即带执行位
git pull origin master
```
