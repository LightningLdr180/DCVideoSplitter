param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$ZipPath,

    [string]$Owner = "LightningLdr180",
    [string]$Repo = "DCVideoSplitter",

    [switch]$Draft
)

$ErrorActionPreference = "Stop"

function Read-GitHubTokenFromFile {
    $tokenFile = Join-Path (Split-Path $PSScriptRoot -Parent) "github-token.txt"
    if (-not (Test-Path -LiteralPath $tokenFile)) { return $null }
    $line = Get-Content -LiteralPath $tokenFile -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and $_ -notmatch '^\s*#' } |
        Select-Object -First 1
    if ($line) { return $line }
    return $null
}

$token = $env:GITHUB_TOKEN
if (-not $token) { $token = $env:GH_TOKEN }
if (-not $token) { $token = Read-GitHubTokenFromFile }
if (-not $token) {
    Write-Error "Set GITHUB_TOKEN, GH_TOKEN, or create github-token.txt in the project root."
}

if (-not (Test-Path -LiteralPath $ZipPath)) {
    Write-Error "Zip not found: $ZipPath"
}

$tag = "v$Version"
$zipName = [IO.Path]::GetFileName($ZipPath)
$api = "https://api.github.com/repos/$Owner/$Repo"
$headers = @{
    Authorization        = "Bearer $token"
    Accept               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

function Get-ReleaseByTag {
    try {
        return Invoke-RestMethod -Uri "$api/releases/tags/$tag" -Headers $headers -Method Get
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 404) { return $null }
        throw
    }
}

$release = Get-ReleaseByTag
if (-not $release) {
    $body = @{
        tag_name = $tag
        name     = $Version
        body     = "Windows 64-bit build with bundled FFmpeg."
        draft    = [bool]$Draft
    } | ConvertTo-Json
    $release = Invoke-RestMethod -Uri "$api/releases" -Headers $headers -Method Post -Body $body -ContentType "application/json; charset=utf-8"
    Write-Host "Created release $tag"
} else {
    Write-Host "Release $tag already exists"
}

foreach ($asset in @($release.assets)) {
    if ($asset.name -eq $zipName) {
        Invoke-RestMethod -Uri "$api/releases/assets/$($asset.id)" -Headers $headers -Method Delete | Out-Null
        Write-Host "Removed existing asset: $zipName"
        break
    }
}

$uploadUrl = ($release.upload_url -replace "\{.*$", "") + "?name=$zipName"
$uploadHeaders = @{
    Authorization        = "Bearer $token"
    Accept               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

Invoke-RestMethod -Uri $uploadUrl -Headers $uploadHeaders -Method Post -ContentType "application/zip" -InFile $ZipPath | Out-Null
Write-Host "Uploaded $zipName to $tag"
Write-Host "https://github.com/$Owner/$Repo/releases/tag/$tag"
