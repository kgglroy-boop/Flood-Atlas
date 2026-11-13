#requires -Version 7.0
. "$PSScriptRoot/common.ps1"

try {
    Assert-ProjectDocker
    Write-Host '[PASS] Docker Linux 引擎与 Compose 可用'
    $null = Get-ProjectEnvironment
    Write-Host '[PASS] 本地密码文件已填写（不输出密码）'
    $null = Invoke-ProjectCompose -ComposeArguments @('config', '--quiet')
    Write-Host '[PASS] Compose 配置校验'
    Write-Host '请另外确认 QGIS 可启动。下一步：docker compose up -d --build --wait --wait-timeout 180'
} catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
