#requires -Version 7.0
param([string]$QgisPython='C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"
. "$PSScriptRoot/geoserver-common.ps1"
try {
    $directory=Resolve-TeachingDataset -OutputRoot (Join-Path $ProjectRoot 'data/processed/teaching-v1')
    Assert-PublishedTeachingDataset -DatasetDirectory $directory
    $manifest=Get-Content -LiteralPath (Join-Path $directory 'manifest.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $api=Invoke-RestMethod -NoProxy -Uri 'http://localhost:8000/api/v1/scenarios' -TimeoutSec 10
    if ($api.dataset_id -ne 'teaching-v1' -or $api.generation_id -ne $manifest.generation_id -or
        $api.model_type -ne 'synthetic_demo' -or $api.analysis_srid -ne 32650 -or $api.depth_unit -ne 'm' -or $api.threshold_m -ne .1 -or
        $api.scenarios.Count -ne 2) { throw '情景目录与当前正式数据契约不符。' }
    $catalog=@(Get-TeachingLayerCatalog)
    $steps=@($api.scenarios | ForEach-Object { $scenario=$_; $_.steps | ForEach-Object {
        [pscustomobject]@{scenario_id=$scenario.scenario_id;time_min=$_.time_min;step_id=$_.step_id;layer_id=$_.layer_id;step_code=$_.step_code}
    }})
    if ($steps.Count -ne 6) { throw '情景目录步骤数量不符。' }
    foreach ($item in $catalog) {
        $match=@($steps | Where-Object { $_.scenario_id -ceq $item.scenario_id -and $_.time_min -eq $item.time_min -and
            $_.step_id -ceq $item.step_id -and $_.layer_id -ceq $item.layer_id -and $_.step_code -ceq ('T{0:00}' -f $item.time_min) })
        if ($match.Count -ne 1) { throw '情景目录步骤映射不符。' }
    }
    $base='http://localhost:8080/geoserver/flood/wms'
    $cap=Invoke-WebRequest -NoProxy -Uri "$base`?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities" -TimeoutSec 30
    $xml=[xml]::new();$xml.XmlResolver=$null;$xml.LoadXml((ConvertFrom-GeoServerContent $cap.Content))
    $names=@($xml.SelectNodes('//*[local-name()="Layer"]/*[local-name()="Name"]') | ForEach-Object {$_.InnerText})
    $checkRoot=Join-Path $ProjectRoot 'data/processed/_checks/phase4'
    $null=New-Item -ItemType Directory -Path $checkRoot -Force
    $projected=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.wms.check_phase3','--projected-bbox')
    $bbox=($projected.bbox | ForEach-Object {([double]$_).ToString('R',[Globalization.CultureInfo]::InvariantCulture)}) -join ','
    $counts=@{S01_T00=0;S01_T30=22048;S01_T60=27592;S02_T00=0;S02_T30=25612;S02_T60=29551}
    $results=@(foreach ($item in $catalog) {
        if ($item.layer_id -notin $names -and $item.store_name -notin $names) { throw "图层未发布：$($item.layer_id)" }
        $parameters="SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=$([uri]::EscapeDataString($item.layer_id))&STYLES=&FORMAT=image%2Fpng&TRANSPARENT=true&INTERPOLATIONS=nearest%20neighbor"
        $nativePath=Join-Path $checkRoot "$($item.step_id)-native.png"
        $nativeUrl="$base`?$parameters&SRS=EPSG:32650&BBOX=499990,3399990,502010,3401010&WIDTH=404&HEIGHT=204"
        $response=Invoke-WebRequest -NoProxy -Uri $nativeUrl -Headers @{Origin='http://localhost:5173'} -OutFile $nativePath -PassThru -TimeoutSec 45
        $cors=[string]($response.Headers['Access-Control-Allow-Origin'] -join '')
        if ($cors -ne 'http://localhost:5173') { throw 'WMS CORS 不符。' }
        $native=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.wms.check_phase3','--png',$nativePath,'--reference',(Join-Path $directory "rasters/$($item.raster_name)"))
        if ($native.wet_pixel_count -ne $counts[$item.step_id]) { throw '原生湿像元数不符。' }
        $projectedPath=Join-Path $checkRoot "$($item.step_id)-3857.png"
        $null=Invoke-WebRequest -NoProxy -Uri "$base`?$parameters&SRS=EPSG:3857&BBOX=$bbox&WIDTH=808&HEIGHT=408" -OutFile $projectedPath -TimeoutSec 45
        $arguments=@('-m','tools.wms.check_phase3','--png',$projectedPath)
        if ($item.time_min -eq 0) { $arguments+='--expect-empty' }
        $web=Invoke-QgisData -QgisPython $QgisPython -ArgumentList $arguments
        if ($web.width -ne 808 -or $web.height -ne 408) { throw '投影响应尺寸不符。' }
        [ordered]@{step_id=$item.step_id;layer_id=$item.layer_id;native=$native;projected=$web;cors=$cors;native_request=$nativeUrl}
    })
    Assert-HealthyApi
    $report=[ordered]@{status='ok';captured_at=(Get-Date -Format o);generation_id=$manifest.generation_id;catalog=$api;layers=$results;source_files='read-only'}
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $checkRoot 'verification.json') -Encoding utf8
    Write-Host '[PASS] 六步骤目录、原生逐像元掩膜、3857地图及CORS全部通过'
    $report | ConvertTo-Json -Depth 12
} catch { Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red;exit 1 }
