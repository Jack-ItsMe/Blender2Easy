@echo off
setlocal
chcp 65001 >nul
set "ANIMATION_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%ANIMATION_PYTHON%" (
  "%ANIMATION_PYTHON%" "%~dp0editor\launch.py"
) else (
  py -3 "%~dp0editor\launch.py"
)
if errorlevel 1 (
  echo 编辑器启动失败。请检查 Python、Blender 和端口 8766。按任意键关闭。
  pause >nul
)
