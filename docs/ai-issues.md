# 本次实际发现与修正的问题

这些问题真实发生于阶段1实现与复测。AI01和AI02首次故障时的代码尚未提交；AI03由独立代码审查在提交1f47261中发现。以下如实记录初始版本、报错和修正，均待负责人复核。

## AI01 TypeScript与Vue类型工具不兼容

初始选择：TypeScript7.0.2与vue-tsc3.3.13。执行npm run type-check报ERR_PACKAGE_PATH_NOT_EXPORTED，vue-tsc访问typescript/lib/tsc，而TypeScript7已改变包导出与编译器结构。

修正：仅将TypeScript固定为6.0.3，重新解析锁文件。重复执行npm run type-check通过，再执行npm ci、前端测试和生产构建均通过。Node类型声明同时与运行时主版本24对齐。

```diff
- "typescript": "7.0.2"
+ "typescript": "6.0.3"
```

## AI02 MapLibre默认Worker路径在Vite预打包后失效

初始代码直接new Map，构建通过，但浏览器出现Worker failed to load，界面显示地图初始化失败。查看MapLibre6.15.0源码，默认Worker路径相对import.meta.url解析；Vite依赖预打包改变模块位置。

修正：由Vite显式处理Worker资源，在地图初始化前设置其URL。

```diff
- import { Map, NavigationControl } from 'maplibre-gl';
+ import { Map, NavigationControl, setWorkerUrl } from 'maplibre-gl';
+ import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
+ setWorkerUrl(workerUrl);
```

复测：开发页面及生产构建预览均显示地图已就绪，缩放与重试控件可操作。生产构建包含独立Worker文件。保留的真实截图见docs/evidence/phase1/frontend-without-database.png。

## 本机代理环境的额外检查

PowerShell默认HTTP请求在本机曾返回502；指定-NoProxy后访问本机API得到真实503及约定JSON。所有本地API和GeoServer管理请求现均显式直连，避免受系统代理影响。该检查没有运行GeoServer，也没有使用真实管理密码。

## AI03 占位密码检查晚于服务初始化

独立审查发现提交1f47261仅在预检和healthcheck拒绝CHANGE_ME，服务可能已用占位密码初始化持久卷。修正为在数据库与GeoServer原初始化入口之前运行共享密码守卫，并让README中的前置检查失败时停止。

先写POSIX守卫测试并观察失败，再实现守卫；3项测试、12种凭据与入口组合通过。测试证明确实没有委托初始化命令，未伪装成真实容器测试。详细审查与待运行项见phase1-review.md。

## AI04 GeoPackage数值落盘类型与QGIS派生文件

第二阶段真实文件测试发现area_m2在生成内存中为整数，GeoPackage的Real字段读回为浮点数，导致严格载荷摘要不一致。诊断确认差异为0与0.0后，改为从实际GeoPackage读出属性和WKB生成载荷，符合数据导出契约。

QGIS读取栅格时还会生成统计aux.xml，导致产物清单多出文件；仅在本次生成进程禁用GDAL PAM侧缓存，TIFF内的单位、NoData和来源仍经重读验证。没有删除既有文件。

## AI05 Windows离屏渲染未加载字体

初次图集视觉检查发现地图存在但所有标题缺失；检查QFontDatabase得到0个字体族。新增标题区域必须有文字像素的测试，观察失败后，在当前QGIS进程注册Windows现有微软雅黑等字体，不安装字体、不更改系统设置。数据测试14项通过，图集包含中英文标题、实际面积/水深及教学声明；图例采用与渲染器一致的连续色带。

## AI06 最终审查的路径与数据库结构保护缺口

独立审查发现临时输出根可入库但保存路径仍指默认挂载，以及同名约束/索引改义未被识别。先新增失败回归，再限制正式发布目录并对全部原始约束及空间索引校验完整定义；SQL迁移SHA256与结构清单绑定。两种数据库改义测试修复前均报DID NOT RAISE，修复后导入和核验均拒绝，原记录保留；脚本6场景及后端28项通过。原未知记录/新增列混合测试的拆分作为Minor延后，未冒充独立结构证据。
