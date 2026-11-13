# GeoServer 运行约定

阶段1使用官方GeoServer3.0.1镜像，跳过演示数据和扩展。运行配置挂载命名卷到/opt/geoserver_data，data/processed只读挂载到/opt/project_data。Java堆为256MiB—1GiB。

工作空间名flood，命名空间URI https://example.org/urban-flood；通过scripts/init-geoserver.ps1创建并核验。GeoServer账号由负责人在.env中填写，后续如在管理页修改账号，应同步考虑容器初始化环境变量的影响。

当前没有水深数据和图层。阶段3先发布一张GeoTIFF及统一SLD，阶段4扩展为六张。后续浏览器直接访问GeoServer，允许来源http://localhost:5173。GWC固定使用EPSG:3857网格，具体瓦片配置待地图阶段验证。

完整GeoServer数据目录可能含凭据，不提交Git；后续使用发布脚本与脱敏配置形成重建依据。
