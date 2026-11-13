#requires -Version 7.0
param([string]$QgisPython = 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $QgisPython -PathType Leaf)) {
    throw 'Set -QgisPython to the python-qgis-ltr.bat path from your QGIS installation.'
}
Push-Location (Split-Path $PSScriptRoot)
try {
    & $QgisPython tools/presentation/nyc_case.py
    if ($LASTEXITCODE) { throw 'The NYC example data preparation failed.' }
} finally { Pop-Location }

