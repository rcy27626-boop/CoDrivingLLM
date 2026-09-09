#!/bin/bash
# ============================================================
# CoDrivingLLM 服务器批量实验运行器
#
# 功能：
#   1. 环境自检（.env.server / Ollama / SILICONFLOW key）
#   2. 按实验矩阵逐格运行，自动断点续跑
#   3. 单格崩溃不终止批次，记录到 batch.log
#   4. 每格结束自动检查 progress.json
#   5. 全部跑完调用 summarize_results.py 出汇总报告
#
# 用法：
#   ./my_workspace/scripts/run_server_batch.sh                    # 全量矩阵（默认）
#   ./my_workspace/scripts/run_server_batch.sh --smoke            # 冒烟模式：每格只跑2轮
#   ./my_workspace/scripts/run_server_batch.sh --scene intersection  # 只跑 intersection
#   ./my_workspace/scripts/run_server_batch.sh --no-video         # 不录视频（加速）
#   ./my_workspace/scripts/run_server_batch.sh --batch 20260905_test  # 指定批次名
#
# 后台运行：
#   nohup ./my_workspace/scripts/run_server_batch.sh > logs/batch_$(date +%Y%m%d_%H%M%S).log 2>&1 &
# ============================================================

set -euo pipefail

# ---- 默认配置 ----
BATCH="20260905_full"
SEED=42
SMOKE=false
NO_VIDEO=false
ONLY_SCENE=""
ONLY_METHODS=""
PYTHON="python"
PART="all"

# ---- 解析命令行参数 ----
while [[ $# -gt 0 ]]; do
    case "$1" in
        --smoke)       SMOKE=true; shift ;;
        --no-video)    NO_VIDEO=true; shift ;;
        --scene)       ONLY_SCENE="$2"; shift 2 ;;
        --methods)     ONLY_METHODS="$2"; shift 2 ;;
        --batch)       BATCH="$2"; shift 2 ;;
        --seed)        SEED="$2"; shift 2 ;;
        --python)      PYTHON="$2"; shift 2 ;;
        --part)        PART="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | head -20
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# ---- 激活 conda 环境（根据服务器实际路径修改）----
if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
    conda activate codrivingllm
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
    conda activate codrivingllm
fi

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
BATCH_LOG="$LOG_DIR/batch_${BATCH}_$(date +%Y%m%d_%H%M%S).log"
RESULT_ROOT="llm_controller/result/$BATCH"

# ---- 日志函数 ----
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$BATCH_LOG"
}

# ============================================================
# 1. 环境自检
# ============================================================
log "========================================"
log "CoDrivingLLM 批量实验启动"
log "批次: $BATCH | 种子: $SEED | 部分: $PART | 冒烟: $SMOKE | 无视频: $NO_VIDEO"
log "日志: $BATCH_LOG"
log "========================================"

# 检查 .env.server
if [ ! -f my_workspace/env/.env.server ]; then
    log "[错误] 未找到 .env.server，请从 .env.example 创建并填写真实配置"
    exit 1
fi
cp my_workspace/env/.env.server .env
log "[OK] .env.server 已复制到 .env"
log "当前模型: $(grep '^LLM_MODEL=' .env | cut -d= -f2)"

# 检查 Ollama 可连接（如果用本地模型）
if grep -q "localhost:11434" .env; then
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        log "[OK] Ollama 服务可连接"
        ollama list 2>/dev/null | grep -q "$(grep '^LLM_MODEL=' .env | cut -d= -f2)" && \
            log "[OK] 模型 $(grep '^LLM_MODEL=' .env | cut -d= -f2) 已存在" || \
            log "[警告] 模型 $(grep '^LLM_MODEL=' .env | cut -d= -f2) 可能未拉取，运行时会自动拉取"
    else
        log "[错误] Ollama 服务不可连接，请先启动: sudo systemctl start ollama"
        exit 1
    fi
fi

# 检查 SILICONFLOW key（记忆模块依赖）
if grep -q "SILICONFLOW_API_KEY=sk-" .env; then
    log "[OK] SILICONFLOW_API_KEY 已配置（记忆嵌入用）"
else
    log "[警告] SILICONFLOW_API_KEY 未配置或无效，--memory-update 建库将失败"
fi

# 检查 Python 依赖
$PYTHON -c "import gym, highway_env, openpyxl, imageio, openai, langchain, chromadb" 2>/dev/null && \
    log "[OK] Python 依赖齐全" || \
    log "[警告] Python 依赖可能不全，运行时可能报错"

# ============================================================
# 2. 定义实验矩阵
# ============================================================
# 格式：场景|方法|轮次|是否建库(memory-update)
# Phase A: 建库 + 0shot 正式实验（合并）
# Phase B: 其余方法
# 分三部分，用 --part 1/2/3 选择，默认 all
# Part 1: 建库 + 0shot 正式实验（必须先跑，2shot/5shot 依赖记忆库）
declare -a PART1_BUILD=(
    "intersection|0shot|30|true"
    "merge|0shot|20|true"
)

# Part 2: intersection 消融实验（no-negotiation / 2shot / 5shot）
declare -a PART2_INTERSECTION=(
    "intersection|no-negotiation|30|false"
    "intersection|2shot|30|false"
    "intersection|5shot|30|false"
)

# Part 3: merge 消融实验（no-negotiation / 2shot / 5shot）
declare -a PART3_MERGE=(
    "merge|no-negotiation|20|false"
    "merge|2shot|20|false"
    "merge|5shot|20|false"
)

# 根据 --part 选择运行哪些部分
declare -a EXPERIMENTS=()
case "$PART" in
    1|build)       EXPERIMENTS=("${PART1_BUILD[@]}") ;;
    2|intersection) EXPERIMENTS=("${PART2_INTERSECTION[@]}") ;;
    3|merge)       EXPERIMENTS=("${PART3_MERGE[@]}") ;;
    all)           EXPERIMENTS=("${PART1_BUILD[@]}" "${PART2_INTERSECTION[@]}" "${PART3_MERGE[@]}") ;;
    *)             echo "未知 --part: $PART（可选 1/build, 2/intersection, 3/merge, all）"; exit 1 ;;
esac

# 冒烟模式：每格只跑2轮
if [ "$SMOKE" = true ]; then
    log "[冒烟模式] 每格只跑 2 轮"
    for i in "${!EXPERIMENTS[@]}"; do
        IFS='|' read -r scene method rounds mem_update <<< "${EXPERIMENTS[$i]}"
        EXPERIMENTS[$i]="${scene}|${method}|2|${mem_update}"
    done
fi

# 场景过滤
if [ -n "$ONLY_SCENE" ]; then
    log "[过滤] 只跑场景: $ONLY_SCENE"
    FILTERED=()
    for exp in "${EXPERIMENTS[@]}"; do
        IFS='|' read -r scene method rounds mem_update <<< "$exp"
        if [ "$scene" = "$ONLY_SCENE" ]; then
            FILTERED+=("$exp")
        fi
    done
    EXPERIMENTS=("${FILTERED[@]}")
fi

# 方法过滤
if [ -n "$ONLY_METHODS" ]; then
    log "[过滤] 只跑方法: $ONLY_METHODS"
    FILTERED=()
    for exp in "${EXPERIMENTS[@]}"; do
        IFS='|' read -r scene method rounds mem_update <<< "$exp"
        if echo "$ONLY_METHODS" | grep -q "$method"; then
            FILTERED+=("$exp")
        fi
    done
    EXPERIMENTS=("${FILTERED[@]}")
fi

TOTAL_EXPS=${#EXPERIMENTS[@]}
log "实验矩阵: $TOTAL_EXPS 个格子"
for exp in "${EXPERIMENTS[@]}"; do
    IFS='|' read -r scene method rounds mem_update <<< "$exp"
    log "  - $scene / $method / ${rounds}轮 / 建库=$mem_update"
done

# ============================================================
# 3. 逐格运行
# ============================================================
BATCH_START=$(date +%s)
SUCCESS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

for idx in "${!EXPERIMENTS[@]}"; do
    IFS='|' read -r scene method rounds mem_update <<< "${EXPERIMENTS[$idx]}"
    CELL_NUM=$((idx + 1))
    log ""
    log "========================================"
    log "[$CELL_NUM/$TOTAL_EXPS] 开始: $scene / $method / ${rounds}轮"
    log "========================================"

    # 检查是否已完成（progress.json 中已有 >= rounds 条记录且无 error）
    PROGRESS_FILE="$RESULT_ROOT/$scene/$method/progress.json"
    DONE_ROUNDS=0
    if [ -f "$PROGRESS_FILE" ]; then
        DONE_ROUNDS=$($PYTHON -c "
import json, sys
try:
    with open('$PROGRESS_FILE') as f:
        data = json.load(f)
    # 统计成功完成的轮次（无 error 字段）
    done = sum(1 for v in data.values() if 'error' not in v)
    print(done)
except:
    print(0)
" 2>/dev/null || echo 0)
    fi

    if [ "$DONE_ROUNDS" -ge "$rounds" ]; then
        log "[跳过] $scene/$method 已完成 $DONE_ROUNDS/$rounds 轮"
        SKIP_COUNT=$((SKIP_COUNT + 1))
        continue
    fi

    # 计算还需跑的轮次
    START_ROUND=$DONE_ROUNDS
    REMAINING=$((rounds - DONE_ROUNDS))
    if [ "$DONE_ROUNDS" -gt 0 ]; then
        log "[续跑] 已完成 $DONE_ROUNDS 轮，从第 $START_ROUND 轮继续，还需 $REMAINING 轮"
    fi

    # 构造命令
    CMD="$PYTHON Run_multi_CAV_LLM.py \
        --scene $scene \
        --method $method \
        --n $REMAINING \
        --start $START_ROUND \
        --seed $SEED \
        --batch $BATCH"

    if [ "$mem_update" = "true" ]; then
        CMD="$CMD --memory-update"
    fi
    if [ "$NO_VIDEO" = true ]; then
        CMD="$CMD --no-video"
    fi

    log "执行命令: $CMD"

    # 运行单格（失败不终止批次）
    CELL_START=$(date +%s)
    set +e
    eval $CMD 2>&1 | tee -a "$BATCH_LOG"
    EXIT_CODE=${PIPESTATUS[0]}
    set -e

    CELL_DUR=$(( $(date +%s) - CELL_START ))
    CELL_DUR_MIN=$((CELL_DUR / 60))

    if [ $EXIT_CODE -eq 0 ]; then
        # 再次检查 progress.json 确认完成
        FINAL_ROUNDS=$($PYTHON -c "
import json
try:
    with open('$PROGRESS_FILE') as f:
        data = json.load(f)
    print(len(data))
except:
    print(0)
" 2>/dev/null || echo 0)
        log "[完成] $scene/$method 用时 ${CELL_DUR_MIN} 分钟，progress.json 共 $FINAL_ROUNDS 条记录"
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        log "[失败] $scene/$method 退出码 $EXIT_CODE，用时 ${CELL_DUR_MIN} 分钟，已记录到日志，可单独重跑"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

# ============================================================
# 4. 汇总
# ============================================================
BATCH_DUR=$(( $(date +%s) - BATCH_START ))
BATCH_DUR_H=$((BATCH_DUR / 3600))
BATCH_DUR_M=$(( (BATCH_DUR % 3600) / 60 ))

log ""
log "========================================"
log "批量实验结束"
log "成功: $SUCCESS_COUNT | 失败: $FAIL_COUNT | 跳过: $SKIP_COUNT | 总计: $TOTAL_EXPS"
log "总耗时: ${BATCH_DUR_H}小时${BATCH_DUR_M}分钟"
log "========================================"

# 调用汇总脚本生成报告
if [ -f my_workspace/scripts/summarize_results.py ]; then
    log ""
    log "生成汇总报告..."
    $PYTHON my_workspace/scripts/summarize_results.py --batch "$BATCH" 2>&1 | tee -a "$BATCH_LOG"
fi

log ""
log "完整日志: $BATCH_LOG"
log "结果目录: $RESULT_ROOT"

if [ $FAIL_COUNT -gt 0 ]; then
    log ""
    log "[注意] 有 $FAIL_COUNT 个格子失败，可单独重跑："
    log "  ./my_workspace/scripts/run_server_batch.sh --scene <scene> --methods <method>"
    exit 1
fi

exit 0
