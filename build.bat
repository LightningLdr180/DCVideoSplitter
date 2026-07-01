@echo off
setlocal

cd /d "%~dp0"

set "ZIPNAME=DCVideoSplitter-win64.zip"
if not "%~1"=="" set "ZIPNAME=DCVideoSplitter-%~1-win64.zip"

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

if not exist "dist\DCVideoSplitter\DCVideoSplitter.exe" (
    echo ERROR: dist\DCVideoSplitter\DCVideoSplitter.exe not found after build.
    exit /b 1
)

if not exist "dist\DCVideoSplitter\ffmpeg\ffmpeg.exe" (
    echo ERROR: dist\DCVideoSplitter\ffmpeg\ffmpeg.exe not found after copy.
    exit /b 1
)

echo Creating release zip: dist\%ZIPNAME%
if exist "dist\%ZIPNAME%" del /f "dist\%ZIPNAME%"

tar -a -c -f "dist\%ZIPNAME%" -C dist DCVideoSplitter
if %ERRORLEVEL% neq 0 (
    echo tar failed, trying PowerShell Compress-Archive...
    powershell -NoProfile -Command "Compress-Archive -LiteralPath '%CD%\dist\DCVideoSplitter' -DestinationPath '%CD%\dist\%ZIPNAME%' -Force"
    if errorlevel 1 (
        echo ERROR: Failed to create release zip.
        exit /b 1
    )
)

echo.
echo Build complete.
echo   App:  dist\DCVideoSplitter\DCVideoSplitter.exe
echo   Zip:  dist\%ZIPNAME%
echo.
echo Upload to GitHub Releases:
if not "%~1"=="" (
    echo   release.bat %~1 upload
) else (
    echo   release.bat 1.0.0 upload
)
echo   Or push a tag:  git tag vX.Y.Z ^&^& git push origin vX.Y.Z
