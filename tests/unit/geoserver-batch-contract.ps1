#requires -Version 7.0
$ErrorActionPreference='Stop'
$root=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. "$root/scripts/geoserver-common.ps1"
$sld=Join-Path $root 'geoserver/styles/depth_teaching.sld'
$generation='74e68b2da680e9680f65'
function Assert-Test($condition,$message) { if (-not $condition) { throw $message } }
function Reset-Fake {
    $script:resources=@{'/workspaces/flood.json'='{"workspace":{"name":"flood"}}'; '/namespaces/flood.json'='{"namespace":{"uri":"https://example.org/urban-flood"}}'}
    $script:writes=0; $script:failAt=0
}
function Invoke-GeoServerRequest {
    param($Method='GET',$Path,$Body='',$ContentType='application/json')
    if ($Method -eq 'GET') {
        if ($script:resources.ContainsKey($Path)) { return @{StatusCode=200;Content=$script:resources[$Path]} }
        return @{StatusCode=404;Content=''}
    }
    $script:writes++
    if ($script:writes -eq $script:failAt) { return @{StatusCode=500;Content='secret-password'} }
    if ($Path -match '^/workspaces/flood/coveragestores/(depth_S0[12]_T(?:00|30|60))/external.geotiff') {
        $name=$Matches[1]; $store="/workspaces/flood/coveragestores/$name"
        Assert-Test ($Body -eq "/opt/project_data/teaching-v1/$generation/rasters/$name.tif") 'Source path mismatch'
        $script:resources["$store.json"]=@{coverageStore=@{name=$name;type='GeoTIFF';url="file:$Body";enabled=$true}} | ConvertTo-Json
        $script:resources["$store/coverages/$name.json"]=@{coverage=@{name=$name;srs='EPSG:32650';nativeBoundingBox=@{minx=499990;miny=3399990;maxx=502010;maxy=3401010;crs='EPSG:32650'}}} | ConvertTo-Json -Depth 5
        $script:resources["$store/coverages.json"]=@{coverages=@{coverage=@(@{name=$name})}} | ConvertTo-Json -Depth 5
        $script:resources["/layers/flood:$name.json"]=@{layer=@{type='RASTER';resource=@{name=$name};defaultStyle=@{name='raster'}}} | ConvertTo-Json -Depth 5
    } elseif ($Path -like '*styles*') { $script:resources['/workspaces/flood/styles/depth_teaching.sld']=$Body
    } elseif ($Path -match '^/layers/flood:(depth_S0[12]_T(?:00|30|60)).json$') {
        $layer=$script:resources[$Path] | ConvertFrom-Json
        $layer.layer.defaultStyle=@{name='flood:depth_teaching'}
        $script:resources[$Path]=$layer | ConvertTo-Json -Depth 5
    } else { throw "Unexpected path: $Path" }
    return @{StatusCode=201;Content=''}
}
Reset-Fake
$catalog=@(Get-TeachingLayerCatalog)
Assert-Test ($catalog.Count -eq 6 -and $catalog[0].step_id -eq 'S01_T00' -and $catalog[5].step_id -eq 'S02_T60') 'Catalog order'
$result=Ensure-Phase4Publication -GenerationId $generation -SldPath $sld
Assert-Test ($result.layers.Count -eq 6 -and $script:writes -eq 13) 'First batch publication'
$script:writes=0
$null=Ensure-Phase4Publication -GenerationId $generation -SldPath $sld
Assert-Test ($script:writes -eq 0) 'Repeat must not mutate'
Write-Host 'PASS: six layers and repeat'
$snapshot=$script:resources.Clone()
foreach ($conflict in @('source','alias','disabled','style')) {
    Reset-Fake; $script:resources=$snapshot.Clone()
    # Keep only sixth store and shared style: a sequential publisher would wrongly create the first five.
    foreach ($key in @($script:resources.Keys)) { if ($key -like '*depth_S0*' -and $key -notlike '*depth_S02_T60*') { $script:resources.Remove($key) } }
    $store='/workspaces/flood/coveragestores/depth_S02_T60'
    switch ($conflict) {
        source { $script:resources["$store.json"]=$script:resources["$store.json"].Replace('file:/opt/project_data','file:/owner') }
        alias { $script:resources["$store/coverages.json"]='{"coverages":{"coverage":[{"name":"owner_alias"}]}}' }
        disabled { $script:resources['/layers/flood:depth_S02_T60.json']=$script:resources['/layers/flood:depth_S02_T60.json'].Replace('"type": "RASTER"','"enabled": false, "type": "RASTER"') }
        style { $script:resources['/workspaces/flood/styles/depth_teaching.sld']=$script:resources['/workspaces/flood/styles/depth_teaching.sld'].Replace('#103f67','#ff0000') }
    }
    $rejected=$false
    try { $null=Ensure-Phase4Publication -GenerationId $generation -SldPath $sld } catch { $rejected=$true }
    Assert-Test ($rejected -and $script:writes -eq 0) "Whole-batch preflight $conflict"
}
Write-Host 'PASS: sixth resource conflicts produce zero writes'
Reset-Fake; $script:failAt=3
try { $null=Ensure-Phase4Publication -GenerationId $generation -SldPath $sld; throw 'Expected failure' } catch { Assert-Test (-not $_.Exception.Message.Contains('secret-password')) 'Leaked password' }
Assert-Test ($script:writes -eq 3) 'Failure must stop immediately'
$script:failAt=0
$null=Ensure-Phase4Publication -GenerationId $generation -SldPath $sld
$script:writes=0
$null=Ensure-Phase4Publication -GenerationId $generation -SldPath $sld
Assert-Test ($script:writes -eq 0) 'Resume must converge'
foreach ($id in @('../owner','bad','74E68B2DA680E9680F65')) {
    $rejected=$false
    try { $null=Ensure-Phase4Publication -GenerationId $id -SldPath $sld } catch { $rejected=$true }
    Assert-Test ($rejected -and $script:writes -eq 0) 'Invalid generation was accepted'
}
Write-Host 'PASS: safe resume and generation whitelist'
