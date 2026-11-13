#requires -Version 7.0
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot
Push-Location -LiteralPath $root
try {
    $source='data/processed/cases/nyc-ida'
    foreach($name in @('metadata.json','depth02.tif','depth04.tif','depth05.tif','imagery.tif','buildings.geojson','roads.geojson','water.geojson')) {
        if (!(Test-Path -LiteralPath (Join-Path $source $name) -PathType Leaf)) { throw "纽约案例缺少 $name。请按案例说明准备裁剪数据。" }
    }
    docker compose run --rm --no-deps -T case-worker bootstrap --default `
        --metadata /case-source/metadata.json `
        --depth /case-source/depth02.tif --depth /case-source/depth04.tif --depth /case-source/depth05.tif `
        --imagery /case-source/imagery.tif --buildings /case-source/buildings.geojson `
        --roads /case-source/roads.geojson --water /case-source/water.geojson
    if ($LASTEXITCODE) { throw '纽约案例未完成发布。请查看本次命令的诊断信息。' }
} finally { Pop-Location }
