#requires -Version 7.0
. "$PSScriptRoot/common.ps1"
$AuditK6Image='grafana/k6:2.0.0@sha256:a33a0cfdc4d2483d6b7a3a22e726a499ff2831a671a49239104cd34a9937523c'
function Get-AuditLoadProfiles {
 @(@{vus=1;seconds=10},@{vus=5;seconds=30},@{vus=10;seconds=30},@{vus=20;seconds=30})
}
function Assert-AuditLoadSummary($Summary) {
 if($Summary.metrics.http_req_failed.values.rate -ne 0 -or $Summary.metrics.checks.values.rate -ne 1 -or $Summary.metrics.health_requests.values.count -le 0 -or $Summary.metrics.summary_requests.values.count -le 0){throw 'Load correctness thresholds failed.'}
}
function Assert-AuditServices {
 $rows=@(Invoke-ProjectCompose @('ps','--format','json')|ForEach-Object{$_|ConvertFrom-Json})
 foreach($service in @('db','geoserver','backend','frontend')){
  $match=@($rows|Where-Object Service -eq $service)
  if($match.Count -ne 1 -or $match[0].State -ne 'running' -or $match[0].Health -ne 'healthy'){throw 'Four healthy project services required.'}
 }
}
function New-AuditDockerProcess([string[]]$Arguments) {
 $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=(Get-Command docker).Source
 $info.WorkingDirectory=$ProjectRoot;$info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 foreach($argument in $Arguments){$info.ArgumentList.Add($argument)}
 $process=[Diagnostics.Process]::new();$process.StartInfo=$info
 $null=$process.Start();return $process
}
