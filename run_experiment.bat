@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM  CoDrivingLLM 实验运行器（个人电脑 Windows 版）
REM
REM  用法（位置参数，均可省略，取默认值）：
REM    run_experiment.bat [scene] [method] [n] [start]
REM
REM  示例：
REM    run_experiment.bat                  => 冒烟: intersection 0shot 2 轮
REM    run_experiment.bat intersection 0shot 5
REM    run_experiment.bat merge 0shot 5
REM    run_experiment.bat highway 0shot 5
REM    run_experiment.bat intersection 2shot 20
REM    run_experiment.bat intersection no-negotiation 20 10   (从第10轮续跑)
REM
REM  参数说明：
REM    scene   = intersection | merge | highway
REM    method  = 0shot | 2shot | 5shot | no-negotiation
REM    n       = 本轮总轮次数
REM    start   = 起始轮次（断点续跑，跳过已完成的轮次）
REM ============================================================

set "PY=F:\ProgramFile\Anaconda3\envs\codrivingllm\python.exe"

REM ---- 默认值 ----
set "_scene=intersection"
set "_method=0shot"
set "_n=2"
set "_start=0"

REM ---- 覆盖默认值（位置参数）----
if not "%~1"=="" set "_scene=%~1"
if not "%~2"=="" set "_method=%~2"
if not "%~3"=="" set "_n=%~3"
if not "%~4"=="" set "_start=%~4"

REM ---- 检查本机私密配置是否存在 ----
if exist my_workspace\env\.env.windows goto :have_config
echo [错误] 未找到 .env.windows，请参考 .env.example 创建本机配置（不要把真实 Key 提交到 git）。
exit /b 1

:have_config
REM ---- 加载 Windows 模型配置到 .env ----
echo === 复制 Windows 模型配置到 .env ===
copy /Y my_workspace\env\.env.windows .env > nul

echo === 当前模型 ===
findstr /B "LLM_MODEL" .env

echo.
echo === 开始实验:  scene=%_scene%  method=%_method%  n=%_n%  start=%_start% ===
echo.

"%PY%" Run_multi_CAV_LLM.py --scene %_scene% --method %_method% --n %_n% --start %_start%

echo.
echo === 实验完成 ===
endlocal
