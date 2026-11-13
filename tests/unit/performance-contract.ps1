#requires -Version 7.0
$ErrorActionPreference='Stop'
. "$PSScriptRoot/../../scripts/performance-common.ps1"
$profiles=@(Get-AuditLoadProfiles)
if(($profiles.vus -join ',') -ne '1,5,10,20' -or ($profiles.seconds -join ',') -ne '10,30,30,30'){throw 'Unbounded load profile'}
$good=@{metrics=@{http_req_failed=@{values=@{rate=0}};checks=@{values=@{rate=1}};health_requests=@{values=@{count=1}};summary_requests=@{values=@{count=1}}}}
Assert-AuditLoadSummary $good
foreach($mutation in @('http_req_failed','checks','health_requests')){
 $bad=$good|ConvertTo-Json -Depth 8|ConvertFrom-Json -AsHashtable
 if($mutation -eq 'http_req_failed'){$bad.metrics.http_req_failed.values.rate=.1}
 elseif($mutation -eq 'checks'){$bad.metrics.checks.values.rate=.9}
 else{$bad.metrics.health_requests.values.count=0}
 $rejected=$false;try{Assert-AuditLoadSummary $bad}catch{$rejected=$true}
 if(-not $rejected){throw 'False success load summary accepted'}
}
Write-Host 'PASS: fixed load profiles and fatal summary correctness gates'
