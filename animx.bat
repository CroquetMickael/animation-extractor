@echo off
rem Opens the editor. Any arguments are passed to the CLI instead (e.g. animx.bat extract video.mp4 --dict my_anims).
cd /d "%~dp0"
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m animx ui
) else (
  ".venv\Scripts\python.exe" -m animx %*
)
