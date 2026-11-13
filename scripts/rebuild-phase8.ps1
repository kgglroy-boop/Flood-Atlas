#requires -Version 7.0
param([string]$QgisPython='C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat',[switch]$KeepRunning)
. "$PSScriptRoot/data-common.ps1"
. "$PSScriptRoot/rebuild-common.ps1"
Assert-ProjectDocker
if(@(& git -C $ProjectRoot status --porcelain).Count){throw 'Commit source changes before a clean reconstruction.'}
$commit=(& git -C $ProjectRoot rev-parse HEAD).Trim();if($LASTEXITCODE -or $commit -notmatch '^[0-9a-f]{40}$'){throw 'Committed source required.'}
$name='ufw-rebuild-'+[guid]::NewGuid().ToString('N');Assert-RebuildOwnership $name $name
$root=Join-Path $ProjectRoot "work/phase8/$name";$source=Join-Path $root 'source'
if(Test-Path $root){throw 'Reconstruction output must not exist.'}
foreach($port in @(15432,18080,18000,15173)){if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){throw 'Reconstruction port already occupied.'}}
foreach($volume in @("${name}_pgdata","${name}_geoserver_data")){
 $null=& docker volume inspect $volume 2>$null;if($LASTEXITCODE -eq 0){throw 'Reconstruction volumes must not preexist.'}
}
$originalIds=@(Invoke-ProjectCompose @('ps','--quiet')|Sort-Object)
$null=New-Item -ItemType Directory $source -Force
$zip=Join-Path $root 'committed-source.zip'
& git -C $ProjectRoot archive --format=zip "--output=$zip" $commit
if($LASTEXITCODE){throw 'Source archive failed.'}
Expand-Archive -LiteralPath $zip -DestinationPath $source
if((Test-Path "$source/.env") -or (Test-Path "$source/data/processed/teaching-v1")){throw 'Source archive contains runtime data.'}
$dbPassword=[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
$geoPassword=[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
"POSTGRES_DB=flood`nPOSTGRES_USER=flood`nPOSTGRES_PASSWORD=$dbPassword`nGEOSERVER_ADMIN_USER=admin`nGEOSERVER_ADMIN_PASSWORD=$geoPassword`n"|Set-Content "$source/.env" -Encoding utf8
$report=Join-Path $root 'reconstruction.json';$log=Join-Path $root 'reconstruction.log'
[ordered]@{project=$name;source_commit=$commit;source=$source;ports=@(15432,18080,18000,15173);original_container_ids=$originalIds;secrets='Fresh independent values in ignored source/.env; omitted from records.'}|ConvertTo-Json -Depth 5|Set-Content (Join-Path $root 'identity.json') -Encoding utf8
$info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=(Get-Process -Id $PID).Path
$info.WorkingDirectory=$source;$info.UseShellExecute=$false;$info.CreateNoWindow=$true
$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
foreach($arg in @('-NoProfile','-File',"$source/scripts/rebuild-stack.ps1",'-RunName',$name,'-ReportPath',$report,'-QgisPython',$QgisPython)){ $info.ArgumentList.Add($arg) }
if($KeepRunning){$info.ArgumentList.Add('-KeepRunning')}
$process=[Diagnostics.Process]::new();$process.StartInfo=$info;$null=$process.Start()
$outTask=$process.StandardOutput.ReadToEndAsync();$errTask=$process.StandardError.ReadToEndAsync()
if(-not $process.WaitForExit(1200000)){
 $process.Kill($true);$process.WaitForExit()
 ($outTask.GetAwaiter().GetResult()+"`n"+$errTask.GetAwaiter().GetResult())|Set-Content $log -Encoding utf8
 Assert-RebuildOwnership $name $name
 $null=& docker compose --project-directory $source -f "$source/docker-compose.yml" -f "$source/docker-compose.rebuild.yml" -p $name down 2>$null
 throw "Reconstruction exceeded20 minutes; owned containers stopped, volumes retained: $name."
}
$code=$process.ExitCode
($outTask.GetAwaiter().GetResult()+"`n"+$errTask.GetAwaiter().GetResult())|Set-Content $log -Encoding utf8
$process.Dispose()
$afterIds=@(Invoke-ProjectCompose @('ps','--quiet')|Sort-Object)
if(($originalIds -join ',') -ne ($afterIds -join ',')){throw 'Original container identities changed.'}
$null=New-Item -ItemType Directory (Join-Path $ProjectRoot 'data/processed/_checks/phase8') -Force
@{run=$name;root=$root;source_commit=$commit;original_containers_unchanged=$true;exit_code=$code}|ConvertTo-Json|Set-Content (Join-Path $ProjectRoot 'data/processed/_checks/phase8/latest.json') -Encoding utf8
if($code){throw "Reconstruction failed; sanitized log retained in work/phase8/$name."}
Write-Host "[PASS] clean source reconstruction: $name; original containers unchanged"
Write-Host "Report: $report"
