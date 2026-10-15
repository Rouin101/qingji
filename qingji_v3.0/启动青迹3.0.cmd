@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo 请先安装 Python 并加入 PATH。
  pause
  exit /b 1
)
if not exist "frontend\dist\client\index.html" (
  echo 请先在 frontend 目录安装依赖并运行 npm run build。
  pause
  exit /b 1
)
python -B server.py --port 8770
