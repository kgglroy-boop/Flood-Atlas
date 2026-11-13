#requires -Version 7.0
$ErrorActionPreference='Stop'
. "$PSScriptRoot/../../scripts/gwc-common.ps1"
$target=Get-GwcAuditTarget
if($target.layer -ne 'flood:depth_S02_T60' -or $target.z -ne 15 -or $target.x -ne 27034 -or $target.y -ne 13441){throw 'Wrong controlled cache target'}
$expected=@(13024869.617980957,3598043.7949389666,13026092.610433351,3599266.787391357)
for($i=0;$i -lt 4;$i++){if([Math]::Abs($target.tile[$i]-$expected[$i])-gt .000001){throw 'Does not match actual GWC grid tile bounds'}}
if([Math]::Abs(($target.meta[2]-$target.meta[0])-4*($target.tile[2]-$target.tile[0])) -gt .000001){throw 'Truncation exceeds four tile columns'}
foreach($args in @(@{Layer='other:layer'},@{Z=14},@{X=0},@{Y=0})){
 $rejected=$false;try{$null=Get-GwcAuditTarget @args}catch{$rejected=$true}
 if(-not $rejected){throw 'Broad or foreign cache target accepted'}
}
$script:writes=0
function Invoke-GwcAuditRest($Method,$Path,$Body){
 if($Method -eq 'GET'){return @{status=200;content='{"long-array-array":[]}'}}
 if($Method -ne 'POST' -or $Path -ne '/seed/flood%3Adepth_S02_T60.json'){throw 'Wrong truncation resource'}
 $b=$Body|ConvertFrom-Json
 if($b.seedRequest.type -ne 'truncate' -or $b.seedRequest.zoomStart -ne 15 -or $b.seedRequest.zoomStop -ne 15 -or $b.seedRequest.gridSetId -ne 'EPSG:900913' -or $b.seedRequest.bounds.coords.double.Count -ne 4){throw 'Wrong truncation scope'}
 $script:writes++;return @{status=200;content=''}
}
Invoke-GwcAuditTruncate
if($script:writes -ne 1){throw 'Unexpected cache writes'}
Write-Host 'PASS: controlled GWC layer/zoom/metatile scope, no global cache deletion'
