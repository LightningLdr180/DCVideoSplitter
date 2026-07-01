@echo off
setlocal

cd /d "%~dp0"

if "%~1"=="" (
    echo Usage: release.bat VERSION [upload^|draft]
    echo.
    echo   VERSION   Release version, e.g. 1.0.0  ^(creates tag v1.0.0^)
    echo   upload    Build, then publish to GitHub Releases ^(requires gh CLI^)
    echo   draft     Build, then create a draft release on GitHub ^(requires gh CLI^)
    echo.
    echo Examples:
    echo   release.bat 1.0.0 upload
    echo   release.bat 1.0.0 draft
    echo.
    echo Without upload/draft, only builds the zip ^(same as build.bat VERSION^).
    exit /b 1
)

set "VERSION=%~1"
set "MODE=%~2"
set "TAG=v%VERSION%"
set "ZIP=dist\DCVideoSplitter-%VERSION%-win64.zip"

call build.bat %VERSION%
if errorlevel 1 exit /b 1

if /i not "%MODE%"=="upload" if /i not "%MODE%"=="draft" (
    echo.
    echo Zip ready. To publish: release.bat %VERSION% upload
    exit /b 0
)

where gh >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: GitHub CLI ^(gh^) is not installed.
    echo Install from https://cli.github.com/ then run:  gh auth login
    echo.
    echo Or push tag %TAG% to GitHub — the release workflow will build and upload automatically.
    exit /b 1
)

gh auth status >nul 2>&1
if errorlevel 1 (
    echo ERROR: Not logged in to GitHub. Run:  gh auth login
    exit /b 1
)

if not exist "%ZIP%" (
    echo ERROR: %ZIP% not found.
    exit /b 1
)

set "DRAFT_FLAG="
if /i "%MODE%"=="draft" set "DRAFT_FLAG=--draft"

echo.
echo Publishing %TAG% to GitHub Releases...

gh release view %TAG% >nul 2>&1
if errorlevel 1 (
    gh release create %TAG% "%ZIP%" --title "%VERSION%" --notes "Windows 64-bit build with bundled FFmpeg." %DRAFT_FLAG%
) else (
    gh release upload %TAG% "%ZIP%" --clobber
)

if errorlevel 1 (
    echo ERROR: GitHub release failed.
    exit /b 1
)

echo.
echo Release published: https://github.com/LightningLdr180/DCVideoSplitter/releases/tag/%TAG%
