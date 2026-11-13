#requires -Version 7.0
param([string]$QgisPython='C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"
$dataset=Resolve-TeachingDataset -OutputRoot "$ProjectRoot/data/processed/teaching-v1"
$result=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.delivery.map_package','--dataset',$dataset,'--output',"$ProjectRoot/frontend/public/maps/teaching-snapshot")
Write-Host '[PASS] six offline depth views and independent analysis package with SHA256 manifest'
$result|ConvertTo-Json
