#requires -Version 7.0
param([string]$QgisPython = 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat',
      [string]$OutputRoot = '', [switch]$SkipBuild)
. "$PSScriptRoot/data-common.ps1"
try {
    if (-not $OutputRoot) { $OutputRoot = Join-Path $ProjectRoot 'data/processed/teaching-v1' }
    $directory = Resolve-TeachingDataset -OutputRoot $OutputRoot
    Assert-PublishedTeachingDataset -DatasetDirectory $directory
    $null = Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.data','verify',
        '--contract',(Join-Path $ProjectRoot 'data/metadata/data-contract.json'),'--dataset-dir',$directory)
    Assert-ProjectDocker
    $null = Get-ProjectEnvironment
    if (-not $SkipBuild) {
        Write-Host '正在确认后端镜像和数据库就绪……'
        $null = Invoke-ProjectCompose -ComposeArguments @('up','-d','--build','--wait','--wait-timeout','180','backend')
    }
    $result = Invoke-TeachingDatabase -DatasetDirectory $directory
    Write-Host '[PASS] 教学数据已在事务中导入并逐项复核'
    $result | ConvertTo-Json -Depth 8
} catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
