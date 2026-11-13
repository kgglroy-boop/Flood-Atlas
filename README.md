# Flood Atlas

**可插拔洪涝案例 WebGIS**

Flood Atlas 将水深 GeoTIFF、航拍和城市地物组织为可导入、预检、发布和切换的案例。默认示例复盘纽约皇后区牙买加湾的 2021 年 Ida 暴雨，使用公开模型的三组峰值水深和 USDA NAIP 航拍。首页支持情景切换、卷帘对照、积水面积与地物暴露统计、建筑搜索、点位查询及离线快照。

## 运行纽约示例

需要 Docker Desktop（Linux 容器）、PowerShell 7 和 QGIS LTR。首次运行需联网获取公开示例数据，若 QGIS 装在其他位置请给准备脚本传入 -QgisPython。在仓库根目录执行：

~~~powershell
if (!(Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
notepad .env
~~~

在本机填写 PostgreSQL 与 GeoServer 密码。然后执行：

~~~powershell
pwsh -NoProfile -File scripts/prepare-nyc-example.ps1
docker compose up -d --build --wait
pwsh -NoProfile -File scripts/publish-nyc-case.ps1
~~~

访问 http://localhost:5173/。地图和案例 API 使用本机服务；导入、发布与矢量瓦片需要完整运行环境。停止时运行 docker compose stop。

## 教学档案

需要生成与发布早期教学档案时，依次运行 prepare-data.ps1、import-data.ps1、publish-phase4.ps1 和 prepare-map-modules.ps1（均位于 scripts）。生成静态模块后重新构建前端。

## 导入自己的案例

1. 运行 pwsh -NoProfile -File scripts/enable-case-import.ps1 -Copy。
2. 从首页的案例库打开「导入案例」。添加单波段水深 GeoTIFF 并指定单位、阈值和情景或时间步。
3. 按需提供建筑、道路、水系、AOI 与航拍。查看预览统计后再发布。
4. 在案例库切换新旧版本。使用「数据来源」里的导出按钮保存可重新导入的案例包。

同一区域重新发布时可选用旧版配套地物。范围检查在预检阶段执行，浏览器继续访问已经发布的版本。详细格式和离线方式见[案例使用说明](docs/nyc-atlas.md)。

## 架构与审查

- Vue 3 / TypeScript / MapLibre 显示地图、卷帘与交互状态。
- GeoServer / GeoWebCache 提供水深 WMTS，案例版本进入图层与瓦片路径。
- FastAPI / PostGIS 提供统计、建筑搜索、点查及按需 MVT。
- GDAL Worker 对导入数据执行投影、覆盖检查和发布。

空间统计使用案例的米制投影。默认示例用 EPSG:32618 和严格大于 0.10 m 的水深阈值。模型峰值来自预计算数据。示例来源、许可及处理过程见[数据来源](examples/nyc-ida/sources.json)与[纽约案例验收](docs/nyc-atlas-verification.md)。界面和交互审查见[前端代码审查](docs/portal-ui-review.md)。
