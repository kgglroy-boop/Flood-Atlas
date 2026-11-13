#requires -Version 7.0
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. "$root/scripts/geoserver-common.ps1"
$sld = Join-Path $root 'geoserver/styles/depth_teaching.sld'
$relative = 'teaching-v1/74e68b2da680e9680f65/rasters/depth_S02_T60.tif'
$source = "file:/opt/project_data/$relative"
$storePath = '/workspaces/flood/coveragestores/depth_S02_T60'
$coveragePath = "$storePath/coverages/depth_S02_T60.json"
$collectionPath = "$storePath/coverages.json"
$layerPath = '/layers/flood:depth_S02_T60.json'
$stylePath = '/workspaces/flood/styles/depth_teaching.sld'

function Assert-Test([bool]$condition, [string]$message) { if (-not $condition) { throw $message } }
function Reset-Fake {
    $script:catalog = @{
        '/workspaces/flood.json' = '{"workspace":{"name":"flood"}}'
        '/namespaces/flood.json' = '{"namespace":{"uri":"https://example.org/urban-flood"}}'
    }
    $script:writes = 0
    $script:failWrite = $false
}
function Invoke-GeoServerRequest {
    param($Method='GET', $Path, $Body='', $ContentType='application/json')
    if ($Method -eq 'GET') {
        if ($script:catalog.ContainsKey($Path)) { return @{StatusCode=200;Content=$script:catalog[$Path];Headers=@{}} }
        return @{StatusCode=404;Content='';Headers=@{}}
    }
    $script:writes++
    if ($script:failWrite) { return @{StatusCode=500;Content='simulated-password-do-not-print';Headers=@{}} }
    if ($Path -like '*external.geotiff*') {
        Assert-Test ($Body -like '/opt/project_data/*' -and -not $Body.StartsWith('file:')) 'GeoServer 3 external upload requires the absolute filesystem path.'
        $script:catalog["$storePath.json"] = @{coverageStore=@{name='depth_S02_T60';type='GeoTIFF';url="file:$Body";enabled=$true}} | ConvertTo-Json -Depth 5
        $script:catalog[$coveragePath] = '{"coverage":{"name":"depth_S02_T60","srs":"EPSG:32650","nativeBoundingBox":{"minx":499990,"miny":3399990,"maxx":502010,"maxy":3401010,"crs":"EPSG:32650"}}}'
        $script:catalog[$collectionPath] = '{"coverages":{"coverage":[{"name":"depth_S02_T60"}]}}'
        $script:catalog[$layerPath] = '{"layer":{"type":"RASTER","defaultStyle":{"name":"raster"},"resource":{"name":"depth_S02_T60"}}}'
    } elseif ($Path -like '*styles*') {
        $script:catalog[$stylePath] = $Body
    } elseif ($Path -eq $layerPath) {
        $script:catalog[$layerPath] = '{"layer":{"type":"RASTER","defaultStyle":{"name":"depth_teaching","workspace":"flood"},"resource":{"name":"depth_S02_T60"}}}'
    } else { throw 'Unexpected mutation path in fake server.' }
    return @{StatusCode=201;Content='';Headers=@{}}
}
Reset-Fake
$first = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld
Assert-Test ($first.status -eq 'ok' -and $script:writes -ge 3) 'Empty catalog was not published.'
$script:writes = 0
$null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld
Assert-Test ($script:writes -eq 0) 'Repeat publication mutated identical configuration.'
Write-Host 'PASS: first publish and identical repeat'

foreach ($change in @('source','crs','style','bounds','layer')) {
    Reset-Fake
    $null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld
    switch ($change) {
        'source' { $script:catalog["$storePath.json"] = $script:catalog["$storePath.json"].Replace($source,'file:/owner/other.tif') }
        'crs' { $script:catalog[$coveragePath] = $script:catalog[$coveragePath].Replace('32650','4326') }
        'style' { $script:catalog[$stylePath] = $script:catalog[$stylePath].Replace('#103f67','#ff0000') }
        'bounds' { $script:catalog[$coveragePath] = $script:catalog[$coveragePath].Replace('499990','100000') }
        'layer' { $script:catalog[$layerPath] = $script:catalog[$layerPath].Replace('depth_teaching','owner_style') }
    }
    $script:writes = 0
    $rejected = $false
    try { $null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld } catch { $rejected = $true }
    Assert-Test ($rejected -and $script:writes -eq 0) "Conflict $change was not rejected before all writes."
}
Write-Host 'PASS: foreign source, CRS, style, bounds and layer conflicts stop before writes'

Reset-Fake
$script:catalog["$storePath.json"] = @{coverageStore=@{name='depth_S02_T60';type='GeoTIFF';url=$source;enabled=$true}} | ConvertTo-Json
$script:catalog[$collectionPath] = '{"coverages":""}'
$null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld
Assert-Test ($script:catalog.ContainsKey($coveragePath)) 'Partial matching store was not recovered.'
Write-Host 'PASS: matching partial publication can be completed'

Reset-Fake
$script:failWrite = $true
$rejected = $false
try { $null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld } catch {
    $rejected = $true
    Assert-Test (-not $_.Exception.Message.Contains('simulated-password')) 'REST error leaked response content.'
}
Assert-Test ($rejected -and $script:writes -eq 1) 'REST failure did not stop immediately.'
Write-Host 'PASS: server failure stops and sanitizes error'

[xml]$xml = Get-Content -LiteralPath $sld -Raw
$entries = @($xml.SelectNodes('//*[local-name()="ColorMapEntry"]'))
Assert-Test (@($entries | Where-Object { [double]$_.quantity -le 0.10000000149011612 -and $_.opacity -ne '0' }).Count -eq 0) 'Dry/NoData entries are not transparent.'
foreach ($pair in @(@(.101,'#d6eef0'),@(.3,'#a8dce4'),@(.6,'#69bfd0'),@(1,'#3297b5'),@(1.5,'#146a91'),@(2,'#103f67'))) {
    Assert-Test (@($entries | Where-Object { [double]$_.quantity -eq $pair[0] -and $_.color -eq $pair[1] -and $_.opacity -eq '1' }).Count -eq 1) 'Depth palette differs.'
}
Write-Host 'PASS: SLD threshold and scientific palette'

Reset-Fake
$null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld
$qualified = $script:catalog[$layerPath] | ConvertFrom-Json
$qualified.layer.resource.name = 'flood:depth_S02_T60'
$script:catalog[$layerPath] = $qualified | ConvertTo-Json -Depth 6
$script:writes = 0
$null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld
Assert-Test ($script:writes -eq 0) 'Qualified same-workspace resource name must be accepted without mutations.'
Write-Host 'PASS: real qualified coverage resource identity'

$serialized = Get-Content -LiteralPath "$PSScriptRoot/fixtures/depth-geoserver-serialized.sld" -Raw -Encoding utf8
Assert-Test ((ConvertTo-SldSignature $serialized) -eq (ConvertTo-SldSignature (Get-Content $sld -Raw))) 'GeoServer serialization defaults changed a semantically identical style.'
Assert-Test ((ConvertTo-SldSignature $serialized.Replace('extended="true"','extended="false"')) -ne (ConvertTo-SldSignature (Get-Content $sld -Raw))) 'Nondefault rendering changes must not normalize away.'
Write-Host 'PASS: actual GeoServer serialization defaults preserve style identity'
$encoded = [Text.Encoding]::UTF8.GetBytes('<WMS_Capabilities>教学</WMS_Capabilities>')
Assert-Test ((ConvertFrom-GeoServerContent $encoded) -eq '<WMS_Capabilities>教学</WMS_Capabilities>') 'Binary XML response was not decoded as UTF-8.'
Write-Host 'PASS: binary XML HTTP content decodes correctly'

Reset-Fake
$script:catalog["$storePath.json"] = @{coverageStore=@{name='depth_S02_T60';type='GeoTIFF';url=$source;enabled=$true}} | ConvertTo-Json
$script:catalog[$collectionPath] = '{"coverages":{"coverage":[{"name":"owner_alias"}]}}'
$script:writes = 0
$rejected = $false
try { $null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld } catch { $rejected = $true }
Assert-Test ($rejected -and $script:writes -eq 0) 'Unknown same-store coverage was accepted or mutated.'
Write-Host 'PASS: unknown same-store coverage is rejected before any write'

foreach ($disabled in @('coverage','layer')) {
    Reset-Fake
    $null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld
    $path = if ($disabled -eq 'coverage') { $coveragePath } else { $layerPath }
    $object = $script:catalog[$path] | ConvertFrom-Json
    $object.$disabled | Add-Member -NotePropertyName enabled -NotePropertyValue $false -Force
    $script:catalog[$path] = $object | ConvertTo-Json -Depth 8
    $script:writes = 0
    $rejected = $false
    try { $null = Ensure-Phase3Publication -RasterRelativePath $relative -SldPath $sld } catch { $rejected = $true }
    Assert-Test ($rejected -and $script:writes -eq 0) "Disabled $disabled was accepted or changed."
}
Write-Host 'PASS: disabled coverage and layer are rejected without re-enabling'
