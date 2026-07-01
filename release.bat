@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if "%~1"=="" goto usage

set "VERSION=%~1"
set "MODE=%~2"
set "TAG=v%VERSION%"
set "ZIP=dist\DCVideoSplitter-%VERSION%-win64.zip"

if /i "%MODE%"=="tag" goto ci_only
if /i "%MODE%"=="ci" goto ci_only
if /i "%MODE%"=="push-tag" goto ci_only

call build.bat %VERSION%
if errorlevel 1 exit /b 1

if "%MODE%"=="" goto build_done
if /i "%MODE%"=="upload" goto upload
if /i "%MODE%"=="draft" goto upload
if /i "%MODE%"=="ci" goto ci_only
if /i "%MODE%"=="tag" goto ci_only

echo Unknown mode: %MODE%
exit /b 1

:usage
echo Usage: release.bat VERSION [MODE]
echo.
echo   VERSION    Release version, e.g. 1.0.0  ^(tag will be v1.0.0^)
echo.
echo   Modes:
echo     ^(none^)     Build zip only
echo     upload      Build locally, then upload zip to GitHub Releases
echo     draft       Build locally, then create a draft release
echo     ci          Trigger GitHub Actions to build and upload ^(no local upload^)
echo.
echo   Use upload OR ci for a release — not both. upload does not trigger CI.
echo.
echo   Upload auth ^(pick one^):
echo     1. Put your token in github-token.txt ^(gitignored^)
echo     2. Set GITHUB_TOKEN or GH_TOKEN
echo     3. Install GitHub CLI:  gh auth login
echo.
echo   CI mode needs github-token.txt with Actions: Read and write permission.
echo.
echo Examples:
echo   release.bat 1.0.0
echo   release.bat 1.0.0 upload
echo   release.bat 1.0.0 ci
exit /b 1

:build_done
echo.
echo Zip ready: %ZIP%
echo Publish with:  release.bat %VERSION% upload
echo Or CI build:   release.bat %VERSION% ci
exit /b 0

:upload
if not exist "%ZIP%" (
    echo ERROR: %ZIP% not found.
    exit /b 1
)

call :find_gh
if not errorlevel 1 goto upload_gh

if defined GITHUB_TOKEN goto upload_token
if defined GH_TOKEN goto upload_token
if exist "%~dp0github-token.txt" goto upload_token

echo.
echo ERROR: Cannot upload — no GitHub CLI and no API token.
echo.
echo Option A — GitHub CLI:
echo   Install from https://cli.github.com/  then run:  gh auth login
echo   Re-run: release.bat %VERSION% upload
echo.
echo Option B — Token file ^(recommended^):
echo   Create github-token.txt in the project root with your token on one line.
echo   release.bat %VERSION% upload
echo.
echo Option C — Environment variable:
echo   set GITHUB_TOKEN=ghp_...
echo   release.bat %VERSION% upload
echo.
echo Option D — GitHub Actions build ^(no local upload^):
echo   release.bat %VERSION% ci
exit /b 1

:upload_gh
gh auth status >nul 2>&1
if errorlevel 1 (
    echo ERROR: gh is installed but not logged in. Run:  gh auth login
    exit /b 1
)

set "DRAFT_FLAG="
if /i "%MODE%"=="draft" set "DRAFT_FLAG=--draft"

echo.
echo Publishing %TAG% with GitHub CLI...

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
goto published

:upload_token
echo.
echo Publishing %TAG%...

set "DRAFT_ARG="
if /i "%MODE%"=="draft" set "DRAFT_ARG=-Draft"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\upload-release.ps1" -Version "%VERSION%" -ZipPath "%CD%\%ZIP%" %DRAFT_ARG%
if errorlevel 1 exit /b 1
goto published

:ci_only
call :find_gh
if not errorlevel 1 (
    gh auth status >nul 2>&1
    if not errorlevel 1 goto ci_run
)

if defined GITHUB_TOKEN goto ci_run
if defined GH_TOKEN goto ci_run
if exist "%~dp0github-token.txt" goto ci_run

echo.
echo ERROR: Cannot trigger CI — no GitHub CLI login and no API token.
echo.
echo Option A — GitHub CLI ^(recommended^):
echo   gh auth login -s repo,workflow
echo   release.bat %VERSION% ci
echo.
echo Option B — Token file:
echo   github-token.txt needs Actions: Read and write ^(fine-grained^)
echo   or classic scopes: repo + workflow
echo   release.bat %VERSION% ci
exit /b 1

:ci_run
echo.
echo Triggering GitHub Actions release build for %TAG%...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\trigger-ci-release.ps1" -Version "%VERSION%"
if errorlevel 1 exit /b 1

echo.
echo CI build started. Watch progress:
echo https://github.com/LightningLdr180/DCVideoSplitter/actions/workflows/release.yml
exit /b 0

:published
echo.
echo Release published: https://github.com/LightningLdr180/DCVideoSplitter/releases/tag/%TAG%
exit /b 0

:find_gh
where gh >nul 2>&1
if not errorlevel 1 exit /b 0
if exist "%ProgramFiles%\GitHub CLI\gh.exe" (
    set "PATH=%ProgramFiles%\GitHub CLI;%PATH%"
    exit /b 0
)
if exist "%LOCALAPPDATA%\Programs\GitHub CLI\gh.exe" (
    set "PATH=%LOCALAPPDATA%\Programs\GitHub CLI;%PATH%"
    exit /b 0
)
exit /b 1
