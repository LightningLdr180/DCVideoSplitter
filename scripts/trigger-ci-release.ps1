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
    if (-not $token) {
        Write-Error "Set GITHUB_TOKEN, GH_TOKEN, or create github-token.txt in the project root."
    }
    return $token
}

$token = Read-GitHubToken
$api = "https://api.github.com/repos/$Owner/$Repo"
$headers = @{
    Authorization        = "Bearer $token"
    Accept               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$body = @{
    ref    = $Branch
    inputs = @{ version = $Version }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod `
    -Uri "$api/actions/workflows/$WorkflowFile/dispatches" `
    -Headers $headers `
    -Method Post `
    -Body $body `
    -ContentType "application/json; charset=utf-8"

Write-Host "Triggered CI release build for v$Version on branch $Branch"
Write-Host "https://github.com/$Owner/$Repo/actions/workflows/$WorkflowFile"
