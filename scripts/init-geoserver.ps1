#requires -Version 7.0
. "$PSScriptRoot/common.ps1"

try {
    Assert-ProjectDocker
    $headers = Get-GeoServerHeaders
    $baseUri = 'http://localhost:8080/geoserver/rest'
    $workspaceUri = "$baseUri/workspaces/flood.json"
    $namespaceUri = "$baseUri/namespaces/flood.json"
    $expectedUri = 'https://example.org/urban-flood'
    $workspace = Invoke-WebRequest -NoProxy -Uri $workspaceUri -Headers $headers -SkipHttpErrorCheck -TimeoutSec 15
    $created = $false
    if ($workspace.StatusCode -eq 404) {
        $null = Invoke-RestMethod -NoProxy -Method Post -Uri "$baseUri/workspaces" -Headers $headers -ContentType 'application/json' -Body '{"workspace":{"name":"flood"}}' -TimeoutSec 15
        $created = $true
    } elseif ($workspace.StatusCode -ne 200) {
        throw 'GeoServer 工作空间查询失败，请检查本地账号与服务。'
    }
    $namespace = Invoke-WebRequest -NoProxy -Uri $namespaceUri -Headers $headers -SkipHttpErrorCheck -TimeoutSec 15
    $namespaceBody = @{ namespace = @{ prefix = 'flood'; uri = $expectedUri } } | ConvertTo-Json -Compress
    if ($namespace.StatusCode -eq 404) {
        $null = Invoke-RestMethod -NoProxy -Method Post -Uri "$baseUri/namespaces" -Headers $headers -ContentType 'application/json' -Body $namespaceBody -TimeoutSec 15
    } elseif ($namespace.StatusCode -eq 200) {
        $actualUri = ($namespace.Content | ConvertFrom-Json).namespace.uri
        if ($actualUri -ne $expectedUri) {
            if (-not $created) { throw '现有 flood 命名空间 URI 不符；未覆盖，请人工检查。' }
            $null = Invoke-RestMethod -NoProxy -Method Put -Uri $namespaceUri -Headers $headers -ContentType 'application/json' -Body $namespaceBody -TimeoutSec 15
        }
    } else { throw 'GeoServer 命名空间查询失败。' }
    $verifiedWorkspace = Invoke-RestMethod -NoProxy -Uri $workspaceUri -Headers $headers -TimeoutSec 15
    $verifiedNamespace = Invoke-RestMethod -NoProxy -Uri $namespaceUri -Headers $headers -TimeoutSec 15
    if ($verifiedWorkspace.workspace.name -ne 'flood' -or $verifiedNamespace.namespace.uri -ne $expectedUri) {
        throw 'GeoServer 工作空间复核失败。'
    }
    Write-Host '[PASS] flood 工作空间与命名空间已核验；未发布数据图层'
} catch {
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
