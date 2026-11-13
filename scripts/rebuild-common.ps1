#requires -Version 7.0
function Assert-RebuildOwnership([string]$Name,[string]$Expected) {
 if($Name -cne $Expected -or $Name -cnotmatch '^ufw-rebuild-[0-9a-f]{32}$'){throw 'Only this run-owned reconstruction project is allowed.'}
}
function Assert-RebuildConfiguration($Config,[string]$Expected) {
 Assert-RebuildOwnership $Config.name $Expected
 foreach($pair in @(@('db',15432,5432),@('geoserver',18080,8080),@('backend',18000,8000),@('frontend',15173,5173))){
  $ports=@($Config.services[$pair[0]].ports)
  if($ports.Count -ne 1 -or $ports[0].host_ip -cne '127.0.0.1' -or [int]$ports[0].published -ne $pair[1] -or $ports[0].target -ne $pair[2]){throw 'Reconstruction port isolation failed.'}
 }
 foreach($volume in @('pgdata','geoserver_data')){if($Config.volumes[$volume].name -cne "${Expected}_$volume"){throw 'Reconstruction must use new owned named volumes.'}}
}
