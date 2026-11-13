#requires -Version 7.0
. "$PSScriptRoot/common.ps1"

function ConvertFrom-GeoServerContent($Content) {
    if ($Content -is [byte[]]) { return [Text.Encoding]::UTF8.GetString($Content) }
    return [string]$Content
}

function Invoke-GeoServerRequest {
    param([string]$Method = 'GET', [Parameter(Mandatory)][string]$Path,
          [string]$Body = '', [string]$ContentType = 'application/json')
    if (-not $Path.StartsWith('/') -or $Path.Contains('..') -or $Path.Contains('://')) { throw '非法 GeoServer REST 路径。' }
    try {
        $options = @{Uri="http://localhost:8080/geoserver/rest$Path";Method=$Method;
            Headers=(Get-GeoServerHeaders);NoProxy=$true;SkipHttpErrorCheck=$true;TimeoutSec=30}
        if ($Body) { $options.Body = [Text.Encoding]::UTF8.GetBytes($Body); $options.ContentType = $ContentType }
        $response = Invoke-WebRequest @options
        return @{StatusCode=[int]$response.StatusCode;Content=(ConvertFrom-GeoServerContent $response.Content);Headers=$response.Headers}
    } catch { throw 'GeoServer REST 连接失败；未输出原始错误或认证信息。' }
}

function Get-RestResource([string]$Path) {
    $reply = Invoke-GeoServerRequest -Path $Path
    if ($reply.StatusCode -eq 404) { return $null }
    if ($reply.StatusCode -ne 200) { throw 'GeoServer 读取资源失败。' }
    return $reply.Content
}

function Write-RestResource([string]$Method, [string]$Path, [string]$Body, [string]$ContentType='application/json') {
    $reply = Invoke-GeoServerRequest -Method $Method -Path $Path -Body $Body -ContentType $ContentType
    if ($reply.StatusCode -notin @(200,201,202)) { throw 'GeoServer 写入失败；保留已完成资源，复跑前将重新核验。' }
}

function ConvertTo-SldSignature([string]$Content) {
    $document = [xml]::new()
    $document.XmlResolver = $null
    $document.LoadXml($Content)
    # GeoServer's SLD writer omits default opacity/ramp type and inserts these
    # presentation-only defaults. Keep every nondefault rendering instruction.
    foreach ($node in @($document.SelectNodes('//*[local-name()="RasterSymbolizer"]/*[local-name()="Opacity"]'))) {
        if ([double]$node.InnerText -eq 1) { $null = $node.ParentNode.RemoveChild($node) }
    }
    foreach ($node in @($document.SelectNodes('//*[local-name()="ContrastEnhancement"]'))) {
        if (-not $node.HasAttributes -and -not $node.HasChildNodes) { $null = $node.ParentNode.RemoveChild($node) }
    }
    foreach ($node in @($document.SelectNodes('//*[local-name()="FeatureTypeStyle"]/*[local-name()="Name"]'))) {
        $null = $node.ParentNode.RemoveChild($node)
    }
    foreach ($node in @($document.SelectNodes('//*[local-name()="ColorMap"]'))) {
        if ($node.GetAttribute('type') -eq 'ramp') { $node.RemoveAttribute('type') }
    }
    function Visit-SldNode($node) {
        if ($node.NodeType -eq [Xml.XmlNodeType]::Element) {
            $attributes = @($node.Attributes | Where-Object { $_.NamespaceURI -ne 'http://www.w3.org/2000/xmlns/' } |
                ForEach-Object { '{0}|{1}={2}' -f $_.NamespaceURI,$_.LocalName,$_.Value } | Sort-Object)
            $children = @($node.ChildNodes | ForEach-Object { Visit-SldNode $_ })
            return (@($node.NamespaceURI,$node.LocalName,$attributes,$children) | ConvertTo-Json -Depth 100 -Compress)
        }
        if ($node.NodeType -in @([Xml.XmlNodeType]::Text,[Xml.XmlNodeType]::CDATA) -and $node.Value.Trim()) { return $node.Value.Trim() }
    }
    return Visit-SldNode $document.DocumentElement
}

function Get-TeachingLayerCatalog {
    foreach ($scenario in @('S01','S02')) {
        foreach ($time in @(0,30,60)) {
            $step = '{0}_T{1:00}' -f $scenario,$time
            [pscustomobject]@{scenario_id=$scenario;time_min=$time;step_id=$step;layer_id="flood:depth_$step";store_name="depth_$step";raster_name="depth_$step.tif"}
        }
    }
}
function Assert-TeachingLayerName([string]$Name) {
    if ($Name -cnotin @((Get-TeachingLayerCatalog).store_name)) { throw '不在教学图层白名单中。' }
}
function Assert-TeachingResources($State, [string]$Source, [string]$SldSignature, [string]$Name) {
    Assert-TeachingLayerName $Name
    if ($State.store) {
        $store = ($State.store | ConvertFrom-Json).coverageStore
        if ($store.name -ne $Name -or $store.type -ne 'GeoTIFF' -or $store.url -ne $Source -or -not $store.enabled) {
            throw '现有存储不是本次同来源 GeoTIFF；未覆盖。'
        }
    }
    if ($State.coverage) {
        if (-not $State.store) { throw '现有覆盖缺少已确认来源，停止。' }
        $coverage = ($State.coverage | ConvertFrom-Json).coverage
        if ($coverage.PSObject.Properties['enabled'] -and $coverage.enabled -ne $true) { throw '现有覆盖已禁用；未重新启用或覆盖。' }
        if ($coverage.name -ne $Name -or $coverage.srs -ne 'EPSG:32650') { throw '现有覆盖名称或 CRS 不符。' }
        foreach ($pair in @(@('minx',499990),@('miny',3399990),@('maxx',502010),@('maxy',3401010))) {
            if ([Math]::Abs([double]$coverage.nativeBoundingBox.($pair[0]) - $pair[1]) -gt .01) { throw '现有覆盖原生范围不符。' }
        }
        $crs = $coverage.nativeBoundingBox.crs
        if ($crs -isnot [string]) { $crs = $crs.'$' }
        if ($crs -ne 'EPSG:32650') { throw '现有覆盖原生 CRS 不符。' }
    }
    if ($State.layer) {
        if (-not $State.coverage) { throw '现有图层缺少已确认覆盖，停止。' }
        $layer = ($State.layer | ConvertFrom-Json).layer
        if ($layer.PSObject.Properties['enabled'] -and $layer.enabled -ne $true) { throw '现有图层已禁用；未重新启用或覆盖。' }
        if ($layer.type -ne 'RASTER' -or $layer.resource.name -notin @($Name,"flood:$Name")) { throw '现有图层资源不符。' }
        if ($layer.resource.PSObject.Properties['href'] -and $layer.resource.href -notlike "*/workspaces/flood/coveragestores/$Name/coverages/$Name.json") {
            throw '现有图层指向其他覆盖。'
        }
        $styleName = $layer.defaultStyle.name
        $ownStyle = $styleName -eq 'flood:depth_teaching' -or ($styleName -eq 'depth_teaching' -and
            $layer.defaultStyle.PSObject.Properties['workspace'] -and $layer.defaultStyle.workspace -eq 'flood')
        if (-not $ownStyle -and $styleName -ne 'raster') { throw '现有图层默认样式不同，未覆盖。' }
    }
    if ($State.style -and (ConvertTo-SldSignature $State.style) -ne $SldSignature) { throw '现有同名 SLD 定义不同，未覆盖。' }
    if ($State.store) {
        if (-not $State.coverages) { throw '无法核对现有存储的全部覆盖，停止。' }
        $collection = ($State.coverages | ConvertFrom-Json -AsHashtable).coverages
        if ($collection -is [Collections.IDictionary] -and $collection.Contains('coverage')) {
            $members = @($collection.coverage)
            if ($members.Count -gt 1 -or @($members | Where-Object { $_.name -ne $Name }).Count -gt 0) {
                throw '同一存储含未知或重复覆盖；未修改任何资源。'
            }
        } elseif ($collection -isnot [string] -or $collection -ne '') { throw '覆盖集合结构不符，停止。' }
    } elseif ($State.coverages) { throw '覆盖集合缺少已确认来源存储，停止。' }
}

function Get-TeachingResources([string]$Name) {
    Assert-TeachingLayerName $Name
    $store = "/workspaces/flood/coveragestores/$Name"
    return @{
        store=(Get-RestResource "$store.json")
        coverage=(Get-RestResource "$store/coverages/$Name.json")
        coverages=(Get-RestResource "$store/coverages.json")
        layer=(Get-RestResource "/layers/flood:$Name.json")
        style=(Get-RestResource '/workspaces/flood/styles/depth_teaching.sld')
    }
}

function Ensure-TeachingPublication {
    param([Parameter(Mandatory)][string]$RasterRelativePath, [Parameter(Mandatory)][string]$SldPath)
    if ($RasterRelativePath -cnotmatch '^teaching-v1/[0-9a-f]{20}/rasters/(depth_S0[12]_T(?:00|30|60))\.tif$') { throw '只允许六个已验证教学图层的正式相对路径。' }
    $Name = $Matches[1]
    Assert-TeachingLayerName $Name
    $source = "file:/opt/project_data/$RasterRelativePath"
    $sld = Get-Content -LiteralPath $SldPath -Raw -Encoding utf8
    $signature = ConvertTo-SldSignature $sld
    $workspace = Get-RestResource '/workspaces/flood.json'
    $namespace = Get-RestResource '/namespaces/flood.json'
    if (-not $workspace -or -not $namespace -or ($workspace | ConvertFrom-Json).workspace.name -ne 'flood' -or
        ($namespace | ConvertFrom-Json).namespace.uri -ne 'https://example.org/urban-flood') { throw 'flood工作空间或命名空间不符。' }
    $state = Get-TeachingResources $Name
    Assert-TeachingResources $state $source $signature $Name
    $created = [Collections.Generic.List[string]]::new()
    if (-not $state.style) {
        Write-RestResource 'POST' '/workspaces/flood/styles?name=depth_teaching' $sld 'application/vnd.ogc.sld+xml'
        $created.Add('style')
    }
    if (-not $state.coverage) {
        Write-RestResource 'PUT' "/workspaces/flood/coveragestores/$Name/external.geotiff?configure=first&coverageName=$Name" "/opt/project_data/$RasterRelativePath" 'text/plain'
        $created.Add('coverage')
    }
    $state = Get-TeachingResources $Name
    Assert-TeachingResources $state $source $signature $Name
    if (-not $state.layer) { throw 'GeoServer没有创建预期图层，保留现场。' }
    $current = ($state.layer | ConvertFrom-Json).layer.defaultStyle
    if ($current.name -eq 'raster') {
        Write-RestResource 'PUT' "/layers/flood:$Name.json" '{"layer":{"defaultStyle":{"name":"flood:depth_teaching"}}}'
        $created.Add('default-style')
    }
    $state = Get-TeachingResources $Name
    Assert-TeachingResources $state $source $signature $Name
    if (-not $state.store -or -not $state.coverage -or -not $state.style -or
        ($state.layer | ConvertFrom-Json).layer.defaultStyle.name -eq 'raster') { throw 'GeoServer发布复核不完整。' }
    return @{status='ok';layer="flood:$Name";store=$Name;source=$source;created=@($created)}
}

function Get-Phase3Resources { Get-TeachingResources 'depth_S02_T60' }
function Assert-Phase3Resources($State,[string]$Source,[string]$SldSignature) { Assert-TeachingResources $State $Source $SldSignature 'depth_S02_T60' }
function Ensure-Phase3Publication {
    param([Parameter(Mandatory)][string]$RasterRelativePath,[Parameter(Mandatory)][string]$SldPath)
    if ($RasterRelativePath -cnotmatch '^teaching-v1/[0-9a-f]{20}/rasters/depth_S02_T60\.tif$') { throw '只允许已验证的S02/T60正式相对路径。' }
    Ensure-TeachingPublication -RasterRelativePath $RasterRelativePath -SldPath $SldPath
}
function Ensure-Phase4Publication {
    param([Parameter(Mandatory)][string]$GenerationId,[Parameter(Mandatory)][string]$SldPath)
    if ($GenerationId -cnotmatch '^[0-9a-f]{20}$') { throw '非法教学数据代际。' }
    $sld = Get-Content -LiteralPath $SldPath -Raw -Encoding utf8
    $signature = ConvertTo-SldSignature $sld
    $workspace = Get-RestResource '/workspaces/flood.json'
    $namespace = Get-RestResource '/namespaces/flood.json'
    if (-not $workspace -or -not $namespace -or ($workspace | ConvertFrom-Json).workspace.name -ne 'flood' -or
        ($namespace | ConvertFrom-Json).namespace.uri -ne 'https://example.org/urban-flood') { throw 'flood工作空间或命名空间不符。' }
    # Complete the entire read-only preflight before the first mutation.
    $catalog = @(Get-TeachingLayerCatalog)
    foreach ($item in $catalog) {
        $state = Get-TeachingResources $item.store_name
        Assert-TeachingResources $state "file:/opt/project_data/teaching-v1/$GenerationId/rasters/$($item.raster_name)" $signature $item.store_name
    }
    $results = @(
        foreach ($item in $catalog) {
            Ensure-TeachingPublication -RasterRelativePath "teaching-v1/$GenerationId/rasters/$($item.raster_name)" -SldPath $SldPath
        }
    )
    return @{status='ok';generation_id=$GenerationId;layers=$results}
}
