#!/bin/bash
# Linux 服务器启动脚本
# 复制 .env.server 到 .env，然后跑实验
# 注意：.env.server 含真实 API Key，不入库，由服务器本地维护

set -e

if [ ! -f my_workspace/env/.env.server ]; then
    echo "错误：未找到 .env.server，请参考 .env.example 在服务器上创建（不要把真实 Key 提交到 git）。" >&2
    exit 1
fi

echo "=== 复制服务器配置 ==="
cp my_workspace/env/.env.server .env
echo "=== 当前模型 ==="
grep '^LLM_MODEL' .env || true
echo ""
echo "=== 开始跑实验 ==="
python Run_multi_CAV_LLM.py
