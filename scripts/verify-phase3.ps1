#requires -Version 7.0
param([string]$QgisPython = 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"
. "$PSScriptRoot/geoserver-common.ps1"
try {
    $directory = Resolve-TeachingDataset -OutputRoot (Join-Path $ProjectRoot 'data/processed/teaching-v1')
    Assert-PublishedTeachingDataset -DatasetDirectory $directory
    $base = 'http://localhost:8080/geoserver/flood/wms'
    $capabilities = Invoke-WebRequest -NoProxy -Uri "$base`?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities" -TimeoutSec 30
    $xml = [xml]::new()
    $xml.XmlResolver = $null
    $xml.LoadXml((ConvertFrom-GeoServerContent $capabilities.Content))
    $names = @($xml.SelectNodes('//*[local-name()="Layer"]/*[local-name()="Name"]') | ForEach-Object { $_.InnerText })
    if ('flood:depth_S02_T60' -notin $names -and 'depth_S02_T60' -notin $names) { throw '未找到水深图层，请先运行 publish-phase3.ps1。' }
    $checkRoot = Join-Path $ProjectRoot 'data/processed/_checks/phase3'
    $null = New-Item -ItemType Directory -Path $checkRoot -Force
    $parameters = 'SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=flood%3Adepth_S02_T60&STYLES=&FORMAT=image%2Fpng&TRANSPARENT=true&INTERPOLATIONS=nearest%20neighbor'
    $nativePath = Join-Path $checkRoot 'native.png'
    $nativeUrl = "$base`?$parameters&SRS=EPSG:32650&BBOX=499990,3399990,502010,3401010&WIDTH=404&HEIGHT=204"
    $response = Invoke-WebRequest -NoProxy -Uri $nativeUrl -Headers @{Origin='http://localhost:5173'} -OutFile $nativePath -PassThru -TimeoutSec 45
    $cors = [string]($response.Headers['Access-Control-Allow-Origin'] -join '')
    if ($cors -ne 'http://localhost:5173') { throw 'WMS未返回当前前端的CORS许可。' }
    $native = Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.wms.check_phase3','--png',$nativePath,
        '--reference',(Join-Path $directory 'rasters/depth_S02_T60.tif'))
    if ($native.wet_pixel_count -ne 29551) { throw 'S02/T60可见像元数不符。' }
    $projected = Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.wms.check_phase3','--projected-bbox')
    $bbox = ($projected.bbox | ForEach-Object { ([double]$_).ToString('R',[Globalization.CultureInfo]::InvariantCulture) }) -join ','
    $projectedPath = Join-Path $checkRoot 'web-mercator.png'
    $null = Invoke-WebRequest -NoProxy -Uri "$base`?$parameters&SRS=EPSG:3857&BBOX=$bbox&WIDTH=808&HEIGHT=408" -OutFile $projectedPath -TimeoutSec 45
    $projectedImage = Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.wms.check_phase3','--png',$projectedPath)
    Assert-HealthyApi
    $report = [ordered]@{status='ok';captured_at=(Get-Date -Format o);layer='flood:depth_S02_T60';
        capabilities_layers=$names;native=$native;projected=$projectedImage;projected_bbox=$projected.bbox;
        cors=$cors;api='healthy';native_request=$nativeUrl;source_files='read-only'}
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $checkRoot 'verification.json') -Encoding utf8
    Write-Host '[PASS] WMS原生像元透明度、3857地图、CORS与API健康均通过'
    $report | ConvertTo-Json -Depth 8
} catch { Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
