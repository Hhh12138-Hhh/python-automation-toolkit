@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo   聚合API 每日签到脚本
echo   时间: %date% %time%
echo ==========================================
echo.
python daily_checkin.py %*
echo.
echo 按任意键关闭...
pause >nul
