#requires -Version 7.0
param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$Artifacts,[Parameter(Mandatory)][string]$Output)
. "$PSScriptRoot/data-common.ps1"
if(-not (Test-Path -LiteralPath $Python -PathType Leaf)){throw 'Provide the bundled Python executable.'}
$directory=Resolve-TeachingDataset -OutputRoot "$ProjectRoot/data/processed/teaching-v1"
Assert-PublishedTeachingDataset $directory
Push-Location $ProjectRoot
try{
 & $Python -m tools.delivery.bundle build --repo $ProjectRoot --dataset $directory --artifacts $Artifacts --output $Output
 if($LASTEXITCODE){throw 'Delivery packaging failed; do not submit incomplete output.'}
}finally{Pop-Location}
