#requires -Version 7.0
[CmdletBinding()]
param([switch]$Copy)
$ErrorActionPreference='Stop'
$envFile=Join-Path (Split-Path $PSScriptRoot) '.env'
if (!(Test-Path -LiteralPath $envFile -PathType Leaf)) { throw '请先根据 .env.example 设置本机服务配置。' }
$content=[IO.File]::ReadAllText($envFile)
$match=[regex]::Match($content,'(?m)^FLOOD_IMPORT_TOKEN[ \t]*=[ \t]*([a-fA-F0-9]{64})[ \t]*\r?$')
if (!$match.Success) {
    $key=[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
    $updated=[regex]::Replace($content,'(?m)^FLOOD_IMPORT_TOKEN[ \t]*=[^\r\n]*\r?\n?','')
    [IO.File]::WriteAllText($envFile,$updated.TrimEnd()+[Environment]::NewLine+"FLOOD_IMPORT_TOKEN=$key"+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
} else {
    $key=$match.Groups[1].Value
}
if ($Copy) {
    Set-Clipboard -Value $key
    Write-Output '导入密钥已复制，可粘贴到本机网页的导入向导。'
} else {
    Write-Output '本机导入密钥已配置。启动或重建 backend 容器后生效。'
}
