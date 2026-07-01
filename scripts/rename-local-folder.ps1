# Rename local clone: DCVideoSplittter -> DCVideoSplitter (fix triple-t typo)
# Close Cursor/terminals using this folder before running.

$ErrorActionPreference = "Stop"
$parent = "D:\Coding"
$oldName = "DCVideoSplittter"
$newName = "DCVideoSplitter"
$oldPath = Join-Path $parent $oldName
$newPath = Join-Path $parent $newName

if (-not (Test-Path -LiteralPath $oldPath)) {
    if (Test-Path -LiteralPath $newPath) {
        Write-Host "Already renamed: $newPath"
        exit 0
    }
    Write-Error "Source folder not found: $oldPath"
}

if (Test-Path -LiteralPath $newPath) {
    Write-Error "Target already exists: $newPath"
}

Write-Host "Renaming:"
Write-Host "  $oldPath"
Write-Host "  -> $newPath"
Rename-Item -LiteralPath $oldPath -NewName $newName
Write-Host "Done. Reopen the project from:"
Write-Host "  $newPath"
