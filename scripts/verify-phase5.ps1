#requires -Version 7.0
param([string]$QgisPython='C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"

function Get-AnalysisJson([string]$Uri) {
    try {
        $response=Invoke-WebRequest -NoProxy -Uri $Uri -TimeoutSec 15 -SkipHttpErrorCheck
        if ($response.StatusCode -ne 200) { throw 'HTTP status mismatch' }
        $content=$response.Content
        if ($content -is [byte[]]) { $content=[Text.Encoding]::UTF8.GetString($content) }
        return ($content | ConvertFrom-Json -AsHashtable)
    } catch { throw '分析HTTP请求失败或响应不是有效JSON；未输出原始响应。' }
}

try {
    $directory=Resolve-TeachingDataset -OutputRoot (Join-Path $ProjectRoot 'data/processed/teaching-v1')
    Assert-PublishedTeachingDataset -DatasetDirectory $directory
    $null=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.data','verify','--contract',(Join-Path $ProjectRoot 'data/metadata/data-contract.json'),'--dataset-dir',$directory)
    $manifest=Get-Content -LiteralPath (Join-Path $directory 'manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $reference=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.analysis.reference','--gpkg',(Join-Path $directory 'teaching.gpkg'))
    $root=Join-Path $ProjectRoot 'data/processed/_checks/phase5'
    $null=New-Item -ItemType Directory -Path $root -Force
    $reference | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $root 'qgis-reference.json') -Encoding utf8
    $results=@(foreach ($transport in @(@{name='direct';base='http://127.0.0.1:8000'},@{name='proxy';base='http://127.0.0.1:5173'})) {
        $catalog=Get-AnalysisJson "$($transport.base)/api/v1/scenarios"
        if ($catalog.generation_id -ne $manifest.generation_id) { throw '目录与正式产物代际不一致。' }
        $summaries=@{};$collections=@{};$limited=@{}
        foreach ($scenario in @('S01','S02')) { foreach ($time in @(0,30,60)) {
            $step='{0}_T{1:00}' -f $scenario,$time
            $summaries[$step]=Get-AnalysisJson "$($transport.base)/api/v1/analysis/summary?step_id=$step"
            $collections[$step]=Get-AnalysisJson "$($transport.base)/api/v1/analysis/buildings?step_id=$step"
            $limited[$step]=Get-AnalysisJson "$($transport.base)/api/v1/analysis/buildings?step_id=$step&limit=1"
        }}
        $checks=@(foreach ($kind in @('full','limited')) {
            $features=if ($kind -eq 'full') {$collections} else {$limited}
            $inputPath=Join-Path $root "$($transport.name)-$kind.json"
            @{catalog=$catalog;reference=$reference;summaries=$summaries;collections=$features} | ConvertTo-Json -Depth 35 | Set-Content -LiteralPath $inputPath -Encoding utf8
            $check=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.analysis.check_responses','--input',$inputPath)
            if ($kind -eq 'full' -and @($check.steps | Where-Object { $_.returned_count -ne 200 -or $_.truncated }).Count -gt 0) { throw '默认建筑结果不是完整200栋。' }
            if ($kind -eq 'limited' -and @($check.steps | Where-Object { $_.returned_count -ne 1 -or -not $_.truncated }).Count -gt 0) { throw '限量建筑结果未明确截断。' }
            [ordered]@{kind=$kind;check=$check}
        })
        [ordered]@{transport=$transport.name;checks=$checks}
    })
    $report=[ordered]@{status='ok';captured_at=(Get-Date -Format o);generation_id=$manifest.generation_id;analysis_srid=32650;reference='QGIS geometry operations from read-only GeoPackage';transports=$results}
    $report | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $root 'verification.json') -Encoding utf8
    Write-Host '[PASS] 六步分析、完整建筑集合、limit截断和两个HTTP入口均与QGIS参照一致'
    $report | ConvertTo-Json -Depth 30
} catch { Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red;exit 1 }
