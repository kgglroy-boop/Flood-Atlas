#requires -Version 7.0
$ErrorActionPreference='Stop'
. "$PSScriptRoot/../../scripts/rebuild-common.ps1"
$name='ufw-rebuild-0123456789abcdef0123456789abcdef'
Assert-RebuildOwnership $name $name
foreach($pair in @(@('urban-flood-webgis',$name),@($name,'ufw-rebuild-ffffffffffffffffffffffffffffffff'),@('ufw-rebuild-../bad','ufw-rebuild-../bad'))){
 $rejected=$false;try{Assert-RebuildOwnership $pair[0] $pair[1]}catch{$rejected=$true};if(-not $rejected){throw 'Foreign project cleanup authorized'}
}
$config=@{name=$name;services=@{};volumes=@{pgdata=@{name="${name}_pgdata"};geoserver_data=@{name="${name}_geoserver_data"}}}
foreach($p in @(@('db',15432,5432),@('geoserver',18080,8080),@('backend',18000,8000),@('frontend',15173,5173))){$config.services[$p[0]]=@{ports=@(@{host_ip='127.0.0.1';published="$($p[1])";target=$p[2]})}}
Assert-RebuildConfiguration $config $name
foreach($change in @('appended','public','volume')){
 $bad=$config|ConvertTo-Json -Depth 10|ConvertFrom-Json -AsHashtable
 switch($change){appended{$bad.services.db.ports+=@{host_ip='127.0.0.1';published='5432';target=5432}} public{$bad.services.db.ports[0].host_ip='0.0.0.0'} volume{$bad.volumes.pgdata.name='urban-flood-webgis_pgdata'}}
 $rejected=$false;try{Assert-RebuildConfiguration $bad $name}catch{$rejected=$true};if(-not $rejected){throw 'Unsafe reconstruction config accepted'}
}
Write-Host 'PASS: exact owned reconstruction project, four isolated loopback ports and new named volumes'
