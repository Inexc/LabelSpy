@echo off
chcp 65001 > nul
echo Запуск LabelSpy Bot...
cd /d "%~dp0"
python bot.py
pause
