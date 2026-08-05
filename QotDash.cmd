@echo off
setlocal
py -3 "%~dp0QotDash.py" --watch 30 --max-rows 0 %*
