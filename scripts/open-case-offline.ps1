#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$Archive,
    [string]$Python = 'python',
    [int]$Port = 5174
)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot
$web=Join-Path $root 'frontend/offline-web'
if (!(Test-Path -LiteralPath (Join-Path $web 'index.html'))) { $web=Join-Path $root 'frontend/dist' }
$arguments=@('-m','tools.cases.offline','--web',$web,'--port',$Port)
if ($Archive) { $arguments+=@('--archive',(Resolve-Path -LiteralPath $Archive).Path) }
else { $arguments+=@('--cases',(Join-Path $root 'data/processed/case-library')) }
Push-Location -LiteralPath $root
try {
    & $Python @arguments
    if ($LASTEXITCODE) { throw '离线地图未能启动。请核对 Python 版本及交付目录。' }
} finally { Pop-Location }
