#requires -Version 7.0
. "$PSScriptRoot/../../scripts/common.ps1"

# A disposable fixture is outside the repository; no real project .env is created.
$ProjectRoot = Join-Path ([IO.Path]::GetTempPath()) ('webgis-config-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $ProjectRoot
$fixtureEnv = Join-Path $ProjectRoot '.env'
Set-Content -LiteralPath $fixtureEnv -Value @('POSTGRES_DB=flood', 'POSTGRES_USER=flood', 'POSTGRES_PASSWORD=FixtureOnly123', 'GEOSERVER_ADMIN_USER=admin', 'GEOSERVER_ADMIN_PASSWORD=FixtureOnly456')
$script:ResolvedFixture = @{
    services = @{
        db = @{ environment = @{ POSTGRES_DB = 'flood'; POSTGRES_USER = 'flood'; POSTGRES_PASSWORD = 'already-resolved-$-password' } }
        geoserver = @{ environment = @{ GEOSERVER_ADMIN_USER = 'admin'; GEOSERVER_ADMIN_PASSWORD = 'resolved#other-password' } }
    }
}

function Invoke-ProjectCompose {
    param([string[]]$ComposeArguments)
    if (($ComposeArguments -join ' ') -ne 'config --format json') { throw 'Unexpected Compose call' }
    $script:ResolvedFixture | ConvertTo-Json -Depth 8
}

try {
    $settings = Get-ProjectEnvironment
    if ($settings.POSTGRES_PASSWORD -ne 'already-resolved-$-password') { throw 'Must use effective Compose credentials, not independently parse .env' }
    if ($settings.GEOSERVER_ADMIN_PASSWORD -ne 'resolved#other-password') { throw 'Must preserve resolved special characters' }
    Write-Output 'PASS: effective Compose settings and special-character passwords'

    $script:ResolvedFixture.services.db.environment.POSTGRES_PASSWORD = 'CHANGE_ME'
    $rejected = $false
    try { $null = Get-ProjectEnvironment } catch { $rejected = $true }
    if (-not $rejected) { throw 'Unconfigured passwords must be rejected' }
    Write-Output 'PASS: placeholder credentials are rejected'
} finally {
    # Remove only the two exact disposable items created by this test.
    [IO.File]::Delete($fixtureEnv)
    [IO.Directory]::Delete($ProjectRoot)
}
