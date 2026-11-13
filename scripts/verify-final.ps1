#requires -Version 7.0
param([string]$ToolPython='python',[string]$QgisPython='C:/Program Files/QGIS 3.44.15/bin/python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"
Assert-ProjectDocker
function Check-Exit {if($LASTEXITCODE){throw 'Final verification command failed.'}}
Push-Location $ProjectRoot
try {
 docker compose config --quiet;Check-Exit
 docker compose exec -T -e RUN_POSTGIS_INTEGRATION=1 backend python -m pytest -q -p no:cacheprovider;Check-Exit
 docker compose exec -T frontend sh -c 'npm test && npm run type-check && npm run build';Check-Exit
 foreach($suite in @('data','wms','analysis','engineering')){& $QgisPython -m unittest discover -s "tests/$suite";Check-Exit}
 & $ToolPython -m unittest discover -s tests/delivery;Check-Exit
 & $ToolPython -m unittest discover -s tests/unit -p test_password_guard.py;Check-Exit
 docker compose run --rm --no-deps -T --volume "${ProjectRoot}/tests/performance:/work:ro" frontend node --test /work/contract.test.mjs;Check-Exit
 foreach($name in @('config','data-scripts','geoserver-publish','geoserver-batch','analysis-logging','engineering','gwc','performance','rebuild')){& "$ProjectRoot/tests/unit/$name-contract.ps1"}
 foreach($name in @('smoke-test','verify-data','verify-phase4','verify-phase5','verify-phase7')){& "$PSScriptRoot/$name.ps1"}
 Write-Output 'PASS_FINAL_REGRESSION'
} finally {Pop-Location}
