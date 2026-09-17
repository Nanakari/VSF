@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "VTuberSongFinder.exe" (
    echo Application executable was not found.
    pause
    exit /b 1
)

start "VTuber Song Finder" "%~dp0VTuberSongFinder.exe"
