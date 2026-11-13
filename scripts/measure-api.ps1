#requires -Version 7.0
param([string]$QgisPython='C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat')
. "$PSScriptRoot/data-common.ps1"
. "$PSScriptRoot/performance-common.ps1"
Assert-ProjectDocker;Assert-AuditServices
$network='urban-flood-webgis_default'
$label=(& docker network inspect $network --format '{{ index .Labels "com.docker.compose.project" }}' 2>$null)-join ''
if($LASTEXITCODE -or $label -ne 'urban-flood-webgis'){throw 'Expected local project network missing.'}
$directory=Resolve-TeachingDataset -OutputRoot (Join-Path $ProjectRoot 'data/processed/teaching-v1')
Assert-PublishedTeachingDataset $directory
$manifest=Get-Content (Join-Path $directory 'manifest.json') -Raw|ConvertFrom-Json
$reference=Invoke-QgisData -QgisPython $QgisPython -ArgumentList @('-m','tools.analysis.reference','--gpkg',(Join-Path $directory 'teaching.gpkg'))
$reference=[ordered]@{status=$reference.status;analysis_srid=$reference.analysis_srid;generation_id=$manifest.generation_id;steps=@($reference.steps|Select-Object step_id,flooded_area_m2,affected_building_ids,flooded_road_length_m)}
$base=Join-Path $ProjectRoot 'data/processed/_checks/phase7/load'
$run='run-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
$root=Join-Path $base $run;$null=New-Item -ItemType Directory $root -Force
$resources=Join-Path $root 'resources.csv';$reports=[Collections.Generic.List[object]]::new()
$stats=$null;$load=$null;$containerName=$null;$succeeded=$false;$phase='initial'
try {
 $dockerResources=(& docker info --format '{{.NCPU}} {{.MemTotal}}' 2>$null)-join ''
 if($LASTEXITCODE){throw 'Docker resource limits unavailable.'}
 $ids=@(Invoke-ProjectCompose @('ps','--quiet','db','geoserver','backend','frontend'))
 if($ids.Count -ne 4){throw 'Four container IDs required.'}
 $stats=New-AuditDockerProcess (@('stats','--no-trunc','--format','{{json .}}')+$ids)
 $statsError=$stats.StandardError.ReadToEndAsync();$line=$stats.StandardOutput.ReadLineAsync()
 foreach($profile in @(Get-AuditLoadProfiles)){
  $phase="vu-$($profile.vus)";$target=Join-Path $root $phase;$null=New-Item -ItemType Directory $target
  $reference|ConvertTo-Json -Depth 10|Set-Content (Join-Path $target 'reference.json') -Encoding utf8
  $containerName='phase7-k6-'+[guid]::NewGuid().ToString('N')
  $load=New-AuditDockerProcess @('run','--rm','--name',$containerName,'--network',$network,'--mount',"type=bind,source=$ProjectRoot/tests/performance,target=/work,readonly",'--mount',"type=bind,source=$target,target=/results",$AuditK6Image,'run','--quiet','--no-usage-report','--env',"AUDIT_VUS=$($profile.vus)",'--env',"AUDIT_DURATION=$($profile.seconds)s",'/work/api.js')
  $stdout=$load.StandardOutput.ReadToEndAsync();$stderr=$load.StandardError.ReadToEndAsync();$clock=[Diagnostics.Stopwatch]::StartNew()
  do {
   if($clock.Elapsed.TotalSeconds -gt ($profile.seconds+25)){throw 'Bounded load process timed out.'}
   while($line.IsCompleted){
    $raw=$line.GetAwaiter().GetResult();if($null -eq $raw){throw 'Resource sampler ended early.'}
    $raw=$raw -replace '\x1b\[[0-9;]*[A-Za-z]',''
    if($raw.Trim()){
     $row=$raw|ConvertFrom-Json
     [pscustomobject]@{timestamp=(Get-Date -Format o);phase=$phase;container=$row.Name;cpu_percent=$row.CPUPerc;memory_usage=$row.MemUsage;memory_percent=$row.MemPerc}|Export-Csv -LiteralPath $resources -Append -NoTypeInformation -Encoding utf8
    }
    $line=$stats.StandardOutput.ReadLineAsync()
   }
   Start-Sleep -Milliseconds 200
  }while(-not $load.HasExited)
  $load.WaitForExit();$code=$load.ExitCode
  $stdout.GetAwaiter().GetResult()|Set-Content (Join-Path $target 'stdout.log') -Encoding utf8
  $stderr.GetAwaiter().GetResult()|Set-Content (Join-Path $target 'stderr.log') -Encoding utf8
  if($code -ne 0){throw "k6 $phase failed; failed batch preserved."}
  $summary=Get-Content (Join-Path $target 'summary.json') -Raw|ConvertFrom-Json -AsHashtable
  Assert-AuditLoadSummary $summary
  $reports.Add([ordered]@{vus=$profile.vus;seconds=$profile.seconds;exit_code=$code;health=$summary.metrics.health_duration.values;health_requests=$summary.metrics.health_requests.values.count;health_error_rate=$summary.metrics.health_errors.values.rate;summary=$summary.metrics.summary_duration.values;summary_requests=$summary.metrics.summary_requests.values.count;summary_error_rate=$summary.metrics.summary_errors.values.rate})
  Write-Host "[PASS] $phase $($profile.seconds)s actual HTTP and independent six-step statistics"
  $load.Dispose();$load=$null;$containerName=$null
  if($profile.vus -in @(5,10)){
   # Keep the continuous sampler running while the next batch cools down.
   $phase='cooldown';$cooldown=[Diagnostics.Stopwatch]::StartNew()
   while($cooldown.Elapsed.TotalSeconds -lt 10){
    while($line.IsCompleted){
     $raw=$line.GetAwaiter().GetResult();if($null -eq $raw){throw 'Resource sampler ended early.'}
     $raw=$raw -replace '\x1b\[[0-9;]*[A-Za-z]',''
     if($raw.Trim()){$row=$raw|ConvertFrom-Json;[pscustomobject]@{timestamp=(Get-Date -Format o);phase=$phase;container=$row.Name;cpu_percent=$row.CPUPerc;memory_usage=$row.MemUsage;memory_percent=$row.MemPerc}|Export-Csv $resources -Append -NoTypeInformation -Encoding utf8}
     $line=$stats.StandardOutput.ReadLineAsync()
    };Start-Sleep -Milliseconds 200
   }
  }
 }
 Assert-AuditServices
 $succeeded=$true
} finally {
 if($load){
  if(-not $load.HasExited){$load.Kill($true)}
  $load.WaitForExit()
  $stdout.GetAwaiter().GetResult()|Set-Content (Join-Path $target 'stdout.log') -Encoding utf8
  $stderr.GetAwaiter().GetResult()|Set-Content (Join-Path $target 'stderr.log') -Encoding utf8
  $load.Dispose()
 }
 if($containerName){$null=& docker rm --force $containerName 2>$null}
 if($stats){if(-not $stats.HasExited){$stats.Kill($true)};$stats.Dispose()}
 [ordered]@{status=$(if($succeeded){'ok'}else{'failed'});captured_at=(Get-Date -Format o);generation_id=$manifest.generation_id;image=$AuditK6Image;target='http://backend:8000 on urban-flood-webgis_default';docker_ncpu_memtotal=$dockerResources;sampler='Docker stats continuous stream, approximately 1s; timestamp when received';batches=$reports.ToArray();limitation='Small local sequential health+summary workload; not external-network latency or production capacity.'}|ConvertTo-Json -Depth 12|Set-Content (Join-Path $root 'measurement.json') -Encoding utf8
}
@{run=$run}|ConvertTo-Json|Set-Content (Join-Path $base 'latest.json') -Encoding utf8
Write-Host '[PASS] bounded local load experiment; four services remain healthy'
