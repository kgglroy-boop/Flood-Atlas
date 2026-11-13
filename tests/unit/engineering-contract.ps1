#requires -Version 7.0
$ErrorActionPreference='Stop'
. "$PSScriptRoot/../../scripts/engineering-common.ps1"
$db=@{status='ok';analysis_srid=32650;building_areas_m2=@{B001=2400;B108=2400;B200=2400}}
$qgis=@{status='ok';analysis_srid=32650;building_areas_m2=@{B001=2400;B108=2400;B200=2400}}
Assert-AuditAreas $db $qgis
foreach($change in @('area','srid','missing','status')){
 $bad=$qgis|ConvertTo-Json -Depth 6|ConvertFrom-Json -AsHashtable
 switch($change){area{$bad.building_areas_m2.B001=2401} srid{$bad.analysis_srid=4326} missing{$bad.building_areas_m2.Remove('B200')} status{$bad.status='failed'}}
 $rejected=$false;try{Assert-AuditAreas $db $bad}catch{$rejected=$true}
 if(-not $rejected){throw 'Invalid independent area comparison accepted'}
}
Write-Host 'PASS: independent metric areas, SRID and exact three-building samples'
