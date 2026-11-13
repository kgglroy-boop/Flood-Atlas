#requires -Version 7.0
. "$PSScriptRoot/common.ps1"

function Invoke-DataProcess {
    param([Parameter(Mandatory)][string]$FilePath,
          [string[]]$ArgumentList = @(), [string]$InputText = '')
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $FilePath
    $start.WorkingDirectory = $ProjectRoot
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $encoding = [System.Text.UTF8Encoding]::new($false)
    $start.StandardInputEncoding = $encoding
    $start.StandardOutputEncoding = $encoding
    $start.StandardErrorEncoding = $encoding
    foreach ($argument in $ArgumentList) { $start.ArgumentList.Add($argument) }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    $started = $false
    try {
        $started = $process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.Write($InputText)
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(90000)) {
            $process.Kill($true)
            throw '数据子进程超时。'
        }
        $text = $stdout.GetAwaiter().GetResult()
        $null = $stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw '数据子进程返回失败。' }
        return $text.Trim()
    } catch {
        if ($started -and -not $process.HasExited) { $process.Kill($true) }
        throw '数据子进程执行失败；未输出可能含凭据的原始子进程日志。'
    } finally { $process.Dispose() }
}

function Invoke-QgisData {
    param([Parameter(Mandatory)][string]$QgisPython,
          [Parameter(Mandatory)][string[]]$ArgumentList)
    if (-not (Test-Path -LiteralPath $QgisPython -PathType Leaf)) {
        throw '未找到 QGIS Python，请通过 -QgisPython 指定 python-qgis-ltr.bat。'
    }
    $oldUtf8 = $env:PYTHONUTF8
    $oldQt = $env:QT_QPA_PLATFORM
    $oldEncoding = [Console]::OutputEncoding
    Push-Location -LiteralPath $ProjectRoot
    try {
        $env:PYTHONUTF8 = '1'
        $env:QT_QPA_PLATFORM = 'offscreen'
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        $lines = @(& $QgisPython @ArgumentList 2>&1)
        if ($LASTEXITCODE -ne 0) { throw 'QGIS 数据操作失败；请核对安装依赖和数据契约，已有产物保持不变。' }
        $jsonLines = @($lines | ForEach-Object { $_.ToString() } | Where-Object { $_.StartsWith('{') })
        if ($jsonLines.Count -ne 1) { throw 'QGIS 未返回唯一的有效结果。' }
        $result = $jsonLines[0] | ConvertFrom-Json
        if ($result.status -ne 'ok') { throw 'QGIS 数据检查未通过。' }
        return $result
    } finally {
        Pop-Location
        $env:PYTHONUTF8 = $oldUtf8
        $env:QT_QPA_PLATFORM = $oldQt
        [Console]::OutputEncoding = $oldEncoding
    }
}

function Resolve-TeachingDataset {
    param([Parameter(Mandatory)][string]$OutputRoot)
    $root = [IO.Path]::GetFullPath($OutputRoot)
    $pointerPath = Join-Path $root 'latest.json'
    if (-not (Test-Path -LiteralPath $pointerPath -PathType Leaf)) { throw '缺少 latest.json，请先运行 prepare-data.ps1。' }
    $pointer = Get-Content -LiteralPath $pointerPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($pointer.relative_path -notmatch '^[0-9a-f]{20}$' -or $pointer.generation_id -ne $pointer.relative_path) {
        throw 'latest.json 中的版本目录不合法。'
    }
    $directory = Join-Path $root $pointer.relative_path
    if (-not (Test-Path -LiteralPath (Join-Path $directory 'manifest.json') -PathType Leaf)) {
        throw '当前教学产物不完整，请保留现场并检查生成记录。'
    }
    $resolved = (Resolve-Path -LiteralPath $directory).Path
    if ([IO.Path]::GetRelativePath($root, $resolved).StartsWith('..')) { throw '教学目录超出输出根目录。' }
    return $resolved
}

function Invoke-TeachingDatabase {
    param([Parameter(Mandatory)][string]$DatasetDirectory, [switch]$VerifyOnly)
    Assert-PublishedTeachingDataset -DatasetDirectory $DatasetDirectory
    Assert-ProjectDocker
    $payload = Get-Content -LiteralPath (Join-Path $DatasetDirectory 'import.json') -Raw -Encoding utf8
    $arguments = @('compose','exec','-T','backend','python','-m','app.import_teaching_data')
    if ($VerifyOnly) { $arguments += '--verify-only' }
    $text = Invoke-DataProcess -FilePath (Get-Command docker).Source -ArgumentList $arguments -InputText $payload
    $result = $text | ConvertFrom-Json
    if ($result.status -ne 'ok') { throw '数据库数据操作未通过。' }
    return $result
}

function Assert-PublishedTeachingDataset {
    param([Parameter(Mandatory)][string]$DatasetDirectory)
    $root = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'data/processed/teaching-v1'))
    $directory = [IO.Path]::GetFullPath($DatasetDirectory)
    $relative = [IO.Path]::GetRelativePath($root, $directory)
    if ($relative -notmatch '^[0-9a-f]{20}$') {
        throw '正式导入/数据库核验只允许项目 data/processed/teaching-v1 发布目录；临时输出仅供独立文件复核。'
    }
    # Reject junctions/symlinks below the project: Docker must see these same files.
    $item = Get-Item -LiteralPath $directory
    while ($item.FullName -ne $ProjectRoot) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw '发布目录不能经过符号链接或目录联接。'
        }
        $item = $item.Parent
    }
}
