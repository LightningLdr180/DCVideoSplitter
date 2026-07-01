param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$Owner = "LightningLdr180",
    [string]$Repo = "DCVideoSplitter",
    [string]$Branch = "main",
    [string]$WorkflowFile = "release.yml"
)

$ErrorActionPreference = "Stop"

function Read-GitHubToken {
    $token = $env:GITHUB_TOKEN
    if (-not $token) { $token = $env:GH_TOKEN }
    if (-not $token) {
        $tokenFile = Join-Path (Split-Path $PSScriptRoot -Parent) "github-token.txt"
        if (Test-Path -LiteralPath $tokenFile) {
            $token = Get-Content -LiteralPath $tokenFile -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ -and $_ -notmatch '^\s*#' } |
                Select-Object -First 1
        }
    }
    return $token
}

function Write-WorkflowAuthHelp {
    param([string]$Version)
    Write-Host ""
    Write-Host "Workflow dispatch needs Actions permission on your token." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Fine-grained PAT (github.com/settings/tokens?type=beta):"
    Write-Host "  Repository: $Owner/$Repo"
    Write-Host "  Actions: Read and write"
    Write-Host "  Contents: Read and write"
    Write-Host ""
    Write-Host "Classic PAT (github.com/settings/tokens):"
    Write-Host "  repo  (or public_repo for public repos)"
    Write-Host "  workflow"
    Write-Host ""
    Write-Host "Or use GitHub CLI (often easiest):"
    Write-Host "  gh auth login -s repo,workflow"
    Write-Host "  release.bat $Version ci"
    Write-Host ""
}

function Invoke-GhWorkflowRun {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) { return $false }

    $priorGhToken = $env:GH_TOKEN
    $priorGithubToken = $env:GITHUB_TOKEN
    $token = Read-GitHubToken
    if ($token) {
        $env:GH_TOKEN = $token
        $env:GITHUB_TOKEN = $token
    }

    try {
        & gh auth status *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        & gh workflow run $WorkflowFile `
            --repo "$Owner/$Repo" `
            --ref $Branch `
            -f "version=$Version"
        if ($LASTEXITCODE -ne 0) {
            throw "gh workflow run failed with exit code $LASTEXITCODE"
        }
        return $true
    }
    finally {
        if ($null -eq $priorGhToken) { Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue }
        else { $env:GH_TOKEN = $priorGhToken }
        if ($null -eq $priorGithubToken) { Remove-Item Env:GITHUB_TOKEN -ErrorAction SilentlyContinue }
        else { $env:GITHUB_TOKEN = $priorGithubToken }
    }
}

function Invoke-ApiWorkflowDispatch {
    param([string]$Token)

    $api = "https://api.github.com/repos/$Owner/$Repo"
    $headers = @{
        Authorization          = "Bearer $Token"
        Accept                 = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    $body = @{
        ref    = $Branch
        inputs = @{ version = $Version }
    } | ConvertTo-Json -Depth 3

    try {
        Invoke-RestMethod `
            -Uri "$api/actions/workflows/$WorkflowFile/dispatches" `
            -Headers $headers `
            -Method Post `
            -Body $body `
            -ContentType "application/json; charset=utf-8"
    }
    catch {
        $status = $null
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
        }
        if ($status -eq 403 -or $status -eq 401) {
            Write-WorkflowAuthHelp -Version $Version
        }
        throw
    }
}

if (Invoke-GhWorkflowRun) {
    Write-Host "Triggered CI release build for v$Version on branch $Branch (via GitHub CLI)"
    Write-Host "https://github.com/$Owner/$Repo/actions/workflows/$WorkflowFile"
    exit 0
}

$token = Read-GitHubToken
if (-not $token) {
    Write-WorkflowAuthHelp -Version $Version
    Write-Error "Set GITHUB_TOKEN, GH_TOKEN, create github-token.txt, or run: gh auth login -s repo,workflow"
}

Invoke-ApiWorkflowDispatch -Token $token

Write-Host "Triggered CI release build for v$Version on branch $Branch"
Write-Host "https://github.com/$Owner/$Repo/actions/workflows/$WorkflowFile"
