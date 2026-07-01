@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if "%~1"=="" goto usage

set "VERSION=%~1"
set "MODE=%~2"
set "TAG=v%VERSION%"
set "ZIP=dist\DCVideoSplitter-%VERSION%-win64.zip"

if /i "%MODE%"=="tag" goto tag_only
if /i "%MODE%"=="push-tag" goto tag_only

call build.bat %VERSION%
if errorlevel 1 exit /b 1

if "%MODE%"=="" goto build_done
if /i "%MODE%"=="upload" goto upload
if /i "%MODE%"=="draft" goto upload
if /i "%MODE%"=="tag" goto push_tag
if /i "%MODE%"=="push-tag" goto push_tag

echo Unknown mode: %MODE%
exit /b 1

:usage
echo Usage: release.bat VERSION [MODE]
echo.
echo   VERSION    Release version, e.g. 1.0.0  ^(tag will be v1.0.0^)
echo.
echo   Modes:
echo     ^(none^)     Build zip only
echo     upload      Build, then publish zip to GitHub Releases
echo     draft       Build, then create a draft release
echo     tag         Build, then git tag + push ^(GitHub Actions uploads^)
echo.
echo   Upload options ^(pick one^):
echo     1. Install GitHub CLI:  https://cli.github.com/  then  gh auth login
echo     2. Put your token in github-token.txt ^(gitignored^) in the project root
echo     3. Set GITHUB_TOKEN or GH_TOKEN in the environment
echo     4. Use tag mode — no token needed; CI builds and uploads on tag push
echo.
echo Examples:
echo   release.bat 1.0.0
echo   release.bat 1.0.0 upload
echo   release.bat 1.0.0 tag
exit /b 1

:build_done
echo.
echo Zip ready: %ZIP%
echo Publish with:  release.bat %VERSION% upload
echo Or CI upload:  release.bat %VERSION% tag
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
echo Option D — Let GitHub Actions upload ^(no local upload^):
echo   release.bat %VERSION% tag
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

:tag_only
set "MODE=tag"

:push_tag
where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git is not installed.
    exit /b 1
)

echo.
echo Creating and pushing tag %TAG%...
git rev-parse %TAG% >nul 2>&1
if not errorlevel 1 (
    echo ERROR: Tag %TAG% already exists locally.
    exit /b 1
)

git tag %TAG%
if errorlevel 1 exit /b 1

git push origin %TAG%
if errorlevel 1 (
    echo ERROR: git push failed. Delete local tag with: git tag -d %TAG%
    exit /b 1
)

echo.
echo Tag pushed. GitHub Actions will build and upload the release zip.
echo https://github.com/LightningLdr180/DCVideoSplitter/actions
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
