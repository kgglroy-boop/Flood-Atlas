#requires -Version 7.0
function Assert-AuditAreas($Inventory,$Reference) {
 if($Inventory.status -ne 'ok' -or $Reference.status -ne 'ok' -or $Inventory.analysis_srid -ne 32650 -or $Reference.analysis_srid -ne 32650){throw 'Metric CRS/reference contract failed.'}
 foreach($id in @('B001','B108','B200')){
  $db=$Inventory.building_areas_m2[$id];$qgis=$Reference.building_areas_m2[$id]
  if($null -eq $db -or $null -eq $qgis -or -not [double]::IsFinite([double]$db) -or -not [double]::IsFinite([double]$qgis) -or [Math]::Abs([double]$db-[double]$qgis) -gt .01){throw 'Independent building areas disagree or sample missing.'}
 }
}
