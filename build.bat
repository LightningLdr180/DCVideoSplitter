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

echo Copying ffmpeg\ to dist\DCVideoSplitter\ffmpeg\ ...
if exist "dist\DCVideoSplitter\ffmpeg" rmdir /s /q "dist\DCVideoSplitter\ffmpeg"
mkdir "dist\DCVideoSplitter\ffmpeg"
copy /y "ffmpeg\ffmpeg.exe" "dist\DCVideoSplitter\ffmpeg\" >nul
copy /y "ffmpeg\ffprobe.exe" "dist\DCVideoSplitter\ffmpeg\" >nul
if exist "ffmpeg\README.md" copy /y "ffmpeg\README.md" "dist\DCVideoSplitter\ffmpeg\" >nul
if exist "ffmpeg\LICENSE.txt" copy /y "ffmpeg\LICENSE.txt" "dist\DCVideoSplitter\ffmpeg\" >nul

echo.
echo Build complete: dist\DCVideoSplitter\DCVideoSplitter.exe
echo Zip the dist\DCVideoSplitter folder (includes ffmpeg\) to share.
