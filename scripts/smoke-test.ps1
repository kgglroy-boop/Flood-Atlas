#requires -Version 7.0
. "$PSScriptRoot/common.ps1"

try {
    Assert-ProjectDocker
    $null = Get-ProjectEnvironment
    $null = Invoke-ProjectCompose -ComposeArguments @('config', '--quiet')
    $version = @(Invoke-ProjectCompose -ComposeArguments @('exec', '-T', 'db', 'psql', '-U', 'flood', '-d', 'flood', '-v', 'ON_ERROR_STOP=1', '-Atc', 'SELECT PostGIS_Version();'))
    if ([string]::IsNullOrWhiteSpace(($version -join ''))) { throw 'PostGIS 未返回版本。' }
    Write-Host '[PASS] 数据库连接与 PostGIS 函数'

    Assert-HealthyApi
    Assert-HealthyApi -Uri 'http://localhost:5173/api/v1/health'
    Write-Host '[PASS] API 就绪及 Vite 代理'

    $swagger = Invoke-WebRequest -NoProxy -Uri 'http://localhost:8000/docs' -TimeoutSec 10
    if ($swagger.StatusCode -ne 200 -or $swagger.Content -notmatch 'swagger-ui') { throw 'Swagger 页面检查失败。' }
    $page = Invoke-WebRequest -NoProxy -Uri 'http://localhost:5173/' -TimeoutSec 10
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch 'id="app"') { throw '前端入口检查失败。' }
    Write-Host '[PASS] Swagger 和前端入口（WebGL仍需浏览器人工检查）'

    $capabilities = Invoke-WebRequest -NoProxy -Uri 'http://localhost:8080/geoserver/ows?service=WMS&version=1.3.0&request=GetCapabilities' -TimeoutSec 30
    $xmlSettings = [System.Xml.XmlReaderSettings]::new()
    $xmlSettings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $xmlSettings.XmlResolver = $null
    $reader = [System.Xml.XmlReader]::Create([System.IO.StringReader]::new($capabilities.Content), $xmlSettings)
    try {
        $document = [System.Xml.XmlDocument]::new()
        $document.XmlResolver = $null
        $document.Load($reader)
        if ($document.DocumentElement.LocalName -ne 'WMS_Capabilities') { throw 'WMS返回内容不是有效Capabilities。' }
    } finally { $reader.Dispose() }
    Write-Host '[PASS] GeoServer WMS Capabilities XML'

    $headers = Get-GeoServerHeaders
    $workspace = Invoke-RestMethod -NoProxy -Uri 'http://localhost:8080/geoserver/rest/workspaces/flood.json' -Headers $headers -TimeoutSec 15
    $namespace = Invoke-RestMethod -NoProxy -Uri 'http://localhost:8080/geoserver/rest/namespaces/flood.json' -Headers $headers -TimeoutSec 15
    if ($workspace.workspace.name -ne 'flood' -or $namespace.namespace.uri -ne 'https://example.org/urban-flood') { throw 'flood 工作空间配置不符。' }
    Write-Host '[PASS] flood 工作空间与命名空间'
    Write-Host '冒烟检查通过。故障恢复与持久化检查请单独运行 verify-lifecycle.ps1。'
} catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
