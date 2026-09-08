@echo off
REM Windows laptop startup script
REM Copies .env.windows to .env, then runs experiment

if exist my_workspace\env\.env.windows goto :have_config
echo [错误] 未找到 .env.windows，请参考 .env.example 创建本机配置（不要把真实 Key 提交到 git）。
exit /b 1

:have_config
echo === Copying Windows config ===
copy /Y my_workspace\env\.env.windows .env > nul

REM Only show model name (avoid leaking API key and URL)
echo === Current model: ===
findstr /B "LLM_MODEL" .env

echo.
echo === Starting experiment ===
python Run_multi_CAV_LLM.py
