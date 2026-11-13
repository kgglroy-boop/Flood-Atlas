# 纽约版验收记录

2026-11-12，Windows 11、Docker Compose 和 QGIS LTR。案例版本 bf37267f4becb2844107。原教学档案 v1 同时复测。

| 检查 | 结果 | 原始记录 |
|---|---|---|
| 代码和服务回归 | 221 项代码测试通过，类型检查和构建完成，PowerShell 及在线验收通过 | evidence/nyc-atlas-20261112/regression-summary.txt |
| 分析交叉核验 | QGIS 与 PostGIS 的三个面积、三段总长度、三套建筑 ID 集合相同 | qgis-match.json |
| 缓存和并发 | 三种情景同一张 z18 瓦片首次 MISS，后 5 次均 HIT 且字节一致；固定点位 280 个并发采样结果一致 | perf.json |
| 访问边界和 MVT | 未授权 401、异源 403、非法 CQL 422；有效瓦片 GDAL 解码 2,272 个要素 | api-checks.json、mvt-decoded.json |
| 案例替换 | EPSG:32650 的三步案例预检、发布、导出、重导版本一致；同区仅上传水深时可复用 200 栋建筑和 32 条道路，前后两个版本保留 | api-checks.json、reuse-check.json |
| 显示与交互 | 5 种视口无横向溢出；1440×900 地图高 674 px，占主体栏宽约 76.5%；卷帘键盘调整、情景切换、建筑搜索、独立 MVT 页面可见 | viewports.json、截图 |
| 独立重建 | 从提交源码和两组输入数据启动独立 Compose 项目，三个水深图层返回 200，新版本和统计一致 | clean-rebuild.log |
| 独立离线 | 从经 API 导出的纽约 ZIP，在单独回环端口读取静态界面、影像、水深和相同的复盘统计 | offline.png |

## 复测命令

先按 README 启动并发布。项目根目录运行：

~~~powershell
pwsh -NoProfile -File scripts/verify-final.ps1
~~~

证据目录的 Python 脚本把原始结果写入 work/nyc-final-20261112。先创建该目录；API 导入测试需提前配置本机导入密钥。qgis_check.py 用 QGIS 随附 Python 执行，随后用系统 Python 执行 check_ids.py 比较数据库。perf.py 首次运行的 MISS 依赖新版本或从未请求过的瓦片。

## 边界

纽约版使用公开预计算模型，不同网格的峰值不一定同步。已有教学案例保留原分析契约。性能数据只覆盖本机实验负载。负责人需要亲自完成课程指定的 CQL、MVT、投影与并发人工审查后签字。

