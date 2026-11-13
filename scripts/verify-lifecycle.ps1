#requires -Version 7.0
. "$PSScriptRoot/common.ps1"

$probeCreated = $false
$probeTable = '_phase1_probe_' + [Guid]::NewGuid().ToString('N')
try {
    Assert-ProjectDocker
    $null = Get-ProjectEnvironment
    Assert-HealthyApi
    $headers = Get-GeoServerHeaders
    $workspaceUri = 'http://localhost:8080/geoserver/rest/workspaces/flood.json'
    $namespaceUri = 'http://localhost:8080/geoserver/rest/namespaces/flood.json'
    $namespaceBefore = Invoke-RestMethod -NoProxy -Uri $namespaceUri -Headers $headers -TimeoutSec 15
    if ($namespaceBefore.namespace.uri -ne 'https://example.org/urban-flood') { throw '请先初始化并核对 flood 工作空间。' }

    Write-Host '即将短暂停止本项目数据库，随后自动恢复。'
    try {
        $null = Invoke-ProjectCompose -ComposeArguments @('stop', 'db')
        $response = Invoke-WebRequest -NoProxy -Uri 'http://localhost:8000/api/v1/health' -SkipHttpErrorCheck -TimeoutSec 15
        $body = $response.Content | ConvertFrom-Json
        if ($response.StatusCode -ne 503 -or $body.detail -ne 'database unavailable' -or @($body.PSObject.Properties.Name).Count -ne 1) {
            throw '数据库停止后健康接口未返回约定的503响应。'
        }
        Write-Host '[PASS] 数据库停止时返回脱敏503'
    } finally {
        $null = Invoke-ProjectCompose -ComposeArguments @('up', '-d', '--wait', '--wait-timeout', '180', 'db', 'backend')
    }
    Assert-HealthyApi
    Write-Host '[PASS] 数据库恢复后 API 重新就绪'

    $sql = "CREATE TABLE public.$probeTable (id integer PRIMARY KEY); INSERT INTO public.$probeTable VALUES (1);"
    $null = Invoke-ProjectCompose -ComposeArguments @('exec', '-T', 'db', 'psql', '-U', 'flood', '-d', 'flood', '-v', 'ON_ERROR_STOP=1', '-c', $sql)
    $probeCreated = $true
    Write-Host '即将停止并重新创建本项目容器，保留全部命名卷。'
    try {
        $null = Invoke-ProjectCompose -ComposeArguments @('down')
    } finally {
        $null = Invoke-ProjectCompose -ComposeArguments @('up', '-d', '--wait', '--wait-timeout', '180')
    }
    $count = @(Invoke-ProjectCompose -ComposeArguments @('exec', '-T', 'db', 'psql', '-U', 'flood', '-d', 'flood', '-v', 'ON_ERROR_STOP=1', '-Atc', "SELECT count(*) FROM public.$probeTable;"))
    if (($count -join '').Trim() -ne '1') { throw '数据库持久化记录检查失败。' }
    $workspace = Invoke-RestMethod -NoProxy -Uri $workspaceUri -Headers $headers -TimeoutSec 15
    $namespaceAfter = Invoke-RestMethod -NoProxy -Uri $namespaceUri -Headers $headers -TimeoutSec 15
    if ($workspace.workspace.name -ne 'flood' -or $namespaceAfter.namespace.uri -ne $namespaceBefore.namespace.uri) { throw 'GeoServer 配置持久化检查失败。' }
    Assert-HealthyApi
    Write-Host '[PASS] 数据库记录与 GeoServer 配置在重建后保留'
} catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($probeCreated) {
        try {
            $null = Invoke-ProjectCompose -ComposeArguments @('exec', '-T', 'db', 'psql', '-U', 'flood', '-d', 'flood', '-v', 'ON_ERROR_STOP=1', '-c', "DROP TABLE public.$probeTable;")
            Write-Host '[CLEANUP] 已清理本次生成的唯一探针表'
        } catch { Write-Warning "本次探针表 $probeTable 尚未清理，请待数据库恢复后处理。" }
    }
}
