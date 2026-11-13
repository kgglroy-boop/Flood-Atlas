#requires -Version 7.0
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Invoke-ProjectCompose {
    param([Parameter(Mandatory)][string[]]$ComposeArguments)
    Push-Location -LiteralPath $ProjectRoot
    try {
        $output = @(& docker compose @ComposeArguments 2>&1)
        $resultCode = $LASTEXITCODE
        if ($resultCode -ne 0) {
            throw "Docker Compose 操作失败（退出码 $resultCode）。请在项目目录检查对应服务日志。"
        }
        $output | ForEach-Object { $_.ToString() }
    } finally {
        Pop-Location
    }
}

function Assert-ProjectDocker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw '未发现 docker。请先安装并启动 Docker Desktop，再重新运行。'
    }
    $null = & docker compose version 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose 不可用，请检查 Docker Desktop 安装。' }
    $engine = & docker info --format '{{.OSType}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or "$engine".Trim() -ne 'linux') {
        throw 'Docker Linux 引擎未就绪，请启动 Docker Desktop 并检查 WSL 2 后端。'
    }
}

function Get-ProjectEnvironment {
    $envPath = Join-Path $ProjectRoot '.env'
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        throw '缺少 .env。请复制 .env.example 为 .env，并在本地填写两个密码。'
    }
    # Resolve .env quotes, interpolation and shell overrides exactly once, using Compose.
    # The full configuration stays in memory and is never printed.
    $configJson = @(Invoke-ProjectCompose -ComposeArguments @('config', '--format', 'json')) -join [Environment]::NewLine
    try { $config = $configJson | ConvertFrom-Json } catch { throw '无法读取 Compose 有效配置。' }
    $settings = @{
        POSTGRES_DB = $config.services.db.environment.POSTGRES_DB
        POSTGRES_USER = $config.services.db.environment.POSTGRES_USER
        POSTGRES_PASSWORD = $config.services.db.environment.POSTGRES_PASSWORD
        GEOSERVER_ADMIN_USER = $config.services.geoserver.environment.GEOSERVER_ADMIN_USER
        GEOSERVER_ADMIN_PASSWORD = $config.services.geoserver.environment.GEOSERVER_ADMIN_PASSWORD
    }
    foreach ($key in @('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'GEOSERVER_ADMIN_USER', 'GEOSERVER_ADMIN_PASSWORD')) {
        if (-not $settings.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($settings[$key]) -or $settings[$key] -eq 'CHANGE_ME') {
            throw ".env 中的 $key 尚未配置。"
        }
    }
    if ($settings.POSTGRES_DB -ne 'flood' -or $settings.POSTGRES_USER -ne 'flood') {
        throw '阶段1请保持 POSTGRES_DB=flood、POSTGRES_USER=flood。'
    }
    return $settings
}

function Get-GeoServerHeaders {
    $settings = Get-ProjectEnvironment
    $pair = '{0}:{1}' -f $settings.GEOSERVER_ADMIN_USER, $settings.GEOSERVER_ADMIN_PASSWORD
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
    return @{ Authorization = "Basic $encoded" }
}

function Assert-HealthyApi {
    param([string]$Uri = 'http://localhost:8000/api/v1/health')
    $response = Invoke-WebRequest -NoProxy -Uri $Uri -TimeoutSec 10 -SkipHttpErrorCheck
    if ($response.StatusCode -ne 200) { throw '健康接口未返回 HTTP 200。' }
    $body = $response.Content | ConvertFrom-Json
    if (@($body.PSObject.Properties.Name).Count -ne 1 -or $body.status -ne 'ok') {
        throw '健康接口 JSON 与约定不一致。'
    }
}
