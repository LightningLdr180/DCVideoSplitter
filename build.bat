@echo off
setlocal

cd /d "%~dp0"

if not exist "ffmpeg\ffmpeg.exe" (
    echo ERROR: ffmpeg\ffmpeg.exe not found.
    echo Download FFmpeg from https://github.com/BtbN/FFmpeg-Builds/releases
    echo and place ffmpeg.exe and ffprobe.exe in the ffmpeg\ folder.
    exit /b 1
)

if not exist "ffmpeg\ffprobe.exe" (
    echo ERROR: ffmpeg\ffprobe.exe not found.
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -r requirements.txt -q

echo Building...
pyinstaller --noconfirm DCVideoSplitter.spec

if %ERRORLEVEL% neq 0 (
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete: dist\DCVideoSplitter\DCVideoSplitter.exe
echo Zip the dist\DCVideoSplitter folder to share with your friend.
