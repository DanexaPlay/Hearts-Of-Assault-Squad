# One-time development mod connection. Run manually with Men of War closed.
# Preserves the old dedicated mod outside the game's scanned mods directory.
$ErrorActionPreference = 'Stop'
$bridgeProject = [System.IO.Path]::GetFullPath($PSScriptRoot)
$bridgeConfig = Get-Content -LiteralPath (Join-Path $bridgeProject 'config.json') -Raw | ConvertFrom-Json
$bridgeLive = [System.IO.Path]::GetFullPath([string]$bridgeConfig.mow_live_mod)
$bridgeMods = [System.IO.Path]::GetFullPath((Join-Path ([string]$bridgeConfig.mow) 'mods'))
$bridgeTarget = [System.IO.Path]::GetFullPath((Join-Path $bridgeMods 'HOI4_MoW_Bridge'))
if (-not $bridgeLive.StartsWith($bridgeProject + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The editable mod must be inside this project.'
}
if (-not $bridgeTarget.StartsWith($bridgeMods + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
    [System.IO.Path]::GetFileName($bridgeTarget) -ne 'HOI4_MoW_Bridge') {
    throw 'Unexpected installed mod path.'
}
if (Get-Process -Name 'mowas_2','mowas_2_ed' -ErrorAction SilentlyContinue) {
    throw 'Close Men of War and its editor first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $bridgeLive 'mod.info') -PathType Leaf)) {
    throw 'The prepared editable mod is missing.'
}
$bridgeBackup = $null
if (Test-Path -LiteralPath $bridgeTarget) {
    $bridgeExisting = Get-Item -LiteralPath $bridgeTarget -Force
    if ($bridgeExisting.LinkType) {
        if ([string]$bridgeExisting.Target -eq $bridgeLive) {
            Write-Host 'The mod is already connected.'
            exit 0
        }
        throw 'An existing link points somewhere else; nothing was changed.'
    }
    $bridgeMetadata = Join-Path $bridgeTarget 'mod.info'
    if (-not (Test-Path -LiteralPath $bridgeMetadata -PathType Leaf) -or
        (Get-Content -LiteralPath $bridgeMetadata -Raw) -notmatch 'name\s+"HOI4_MoW_Bridge"') {
        throw 'The installed folder is not our dedicated mod; nothing was changed.'
    }
    $bridgeBackupRoot = Join-Path $bridgeProject 'backups'
    $bridgeBackup = [System.IO.Path]::GetFullPath((Join-Path $bridgeBackupRoot ('mow_installed_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))))
    if (-not $bridgeBackup.StartsWith($bridgeProject + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unexpected backup destination.'
    }
    if (Test-Path -LiteralPath $bridgeBackup) { throw 'Backup already exists.' }
    New-Item -ItemType Directory -Path $bridgeBackupRoot -Force | Out-Null
    Move-Item -LiteralPath $bridgeTarget -Destination $bridgeBackup
}
try {
    New-Item -ItemType Junction -Path $bridgeTarget -Value $bridgeLive | Out-Null
    Write-Host 'Connected. The game reads the mod from the project; old files were preserved.'
    if ($bridgeBackup) { Write-Host ('Backup: ' + $bridgeBackup) }
} catch {
    if ($bridgeBackup -and -not (Test-Path -LiteralPath $bridgeTarget)) {
        Move-Item -LiteralPath $bridgeBackup -Destination $bridgeTarget
    }
    throw
}
