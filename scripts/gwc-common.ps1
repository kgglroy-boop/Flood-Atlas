#requires -Version 7.0
. "$PSScriptRoot/common.ps1"
function Get-GwcAuditTarget {
 param([string]$Layer='flood:depth_S02_T60',[int]$Z=15,[int]$X=27034,[int]$Y=13441)
 if($Layer -cne 'flood:depth_S02_T60' -or $Z -ne 15 -or $X -ne 27034 -or $Y -ne 13441){throw 'Refusing cache target outside approved experiment.'}
 # Exact existing GWC EPSG:900913 grid extent, confirmed against tile headers.
 # The mathematical EPSG:3857 extent differs by millimetres and can change colors.
 $world=40075016.68;$size=$world/[Math]::Pow(2,$Z);$half=$world/2
 @{layer=$Layer;z=$Z;x=$X;y=$Y;tile=@((-$half+$X*$size),($half-($Y+1)*$size),(-$half+($X+1)*$size),($half-$Y*$size));
   meta=@((-$half+27032*$size),($half-13444*$size),(-$half+27036*$size),($half-13440*$size))}
}
function Invoke-GwcAuditRest {
 param([string]$Method,[string]$Path,[string]$Body='')
 if($Path -cne '/seed/flood%3Adepth_S02_T60.json' -or $Method -notin @('GET','POST')){throw 'Unapproved GWC REST operation.'}
 try {
  $options=@{Uri="http://127.0.0.1:8080/geoserver/gwc/rest$Path";Method=$Method;Headers=(Get-GeoServerHeaders);NoProxy=$true;TimeoutSec=30;SkipHttpErrorCheck=$true}
  if($Body){$options.Body=[Text.Encoding]::UTF8.GetBytes($Body);$options.ContentType='application/json'}
  $r=Invoke-WebRequest @options
  $content=$r.Content;if($content -is [byte[]]){$content=[Text.Encoding]::UTF8.GetString($content)}
  @{status=[int]$r.StatusCode;content=[string]$content}
 }catch{throw 'GWC administrative request failed; no raw credentials or diagnostic emitted.'}
}
function Get-GwcActiveJobs {
 $r=Invoke-GwcAuditRest -Method GET -Path '/seed/flood%3Adepth_S02_T60.json'
 if($r.status -ne 200){throw 'Cannot inspect GWC tasks.'}
 $data=$r.content|ConvertFrom-Json
 if(-not $data.PSObject.Properties['long-array-array']){throw 'Unknown GWC task response.'}
 @($data.'long-array-array'|Where-Object {$_[-1] -in @(0,1)})
}
function Invoke-GwcAuditTruncate {
 $target=Get-GwcAuditTarget
 if(@(Get-GwcActiveJobs).Count){throw 'Existing GWC tasks present; do not interrupt them.'}
 $body=@{seedRequest=@{name=$target.layer;gridSetId='EPSG:900913';bounds=@{coords=@{double=$target.meta}};zoomStart=15;zoomStop=15;format='image/png';type='truncate';threadCount=1}}|ConvertTo-Json -Depth 8 -Compress
 $r=Invoke-GwcAuditRest -Method POST -Path '/seed/flood%3Adepth_S02_T60.json' -Body $body
 if($r.status -notin @(200,201,202)){throw 'Controlled GWC truncation failed.'}
 $deadline=[DateTime]::UtcNow.AddSeconds(45)
 while(@(Get-GwcActiveJobs).Count){if([DateTime]::UtcNow -gt $deadline){throw 'GWC task timed out; no unrelated jobs were stopped.'};Start-Sleep -Milliseconds 250}
}
function Get-GwcTileUrl([string]$Layer,[int]$Z,[int]$X,[int]$Y) {
 if($Layer -cnotmatch '^flood:depth_S0[12]_T(00|30|60)$' -or $Z -lt 0 -or $Z -gt 19 -or $X -lt 0 -or $Y -lt 0 -or $X -ge [Math]::Pow(2,$Z) -or $Y -ge [Math]::Pow(2,$Z)){throw 'Invalid controlled WMTS tile'}
 "http://127.0.0.1:8080/geoserver/gwc/service/wmts?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetTile&LAYER=$([uri]::EscapeDataString($Layer))&STYLE=flood%3Adepth_teaching&TILEMATRIXSET=EPSG%3A900913&TILEMATRIX=EPSG%3A900913%3A$Z&TILECOL=$X&TILEROW=$Y&FORMAT=image%2Fpng"
}
