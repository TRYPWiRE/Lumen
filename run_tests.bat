@echo off
cd /d "%~dp0"
python -m unittest discover tests -v
pause
