# 阶段8最终验证记录

## 实际运行

2026-10-20在Windows原项目执行`pwsh -NoProfile -File scripts/verify-final.ps1`，完整日志保留于本机data/processed/_checks/phase8/final-regression.log。实际通过：后端pytest119（RUN_POSTGIS_INTEGRATION=1）；前端Node37、类型检查与生产构建；QGIS data14/wms7/analysis6/engineering5；归档安全5；本机启动密码guard3；Node负载契约3，共199项，另9组PowerShell契约和smoke/verify-data/verify-phase4/verify-phase5/verify-phase7五条运行核验。随后新增视频页面目标校验先RED后GREEN，交付测试6项再通过，总计200项。verify-final脚本已纳入该新增项，后续可一条命令重跑。

未重做k6及缓存清除实验：原阶段7固定实测仍是报告引用的2026请求、冷/热样本。默认verify-phase7只核验，不清全局缓存。MapLibre大包构建提示保留。

## 科学数据及重建

当前代际74e68b2da680e9680f65，语义SHA256=b4929f672ef57d654dcd83086988d02f5b6d4ce5937b7694e147d44ff3b197d2。原科学生成器、迁移和分析SQL与03c32ee保持不变。

新增模块后从提交9caedd2b634ccb8eb04ef7b20f31b4b6d10cfef7导出无.env、无生成数据源码，项目ufw-rebuild-cea12eb1cb1c441187e8a3c155754156，新端口15432/18080/18000/15173和新卷，导入前业务schema=0；重新生成六栅格和快照模块，11项实际服务链核验通过。原容器身份不变，结束停止独立容器并保留卷。证据reconstruction-modules.json及identity.json。后续改动为交付工具/文档/核验脚本；最终release源码提交见manifest，不把不同提交冒充同一次重建。

## 界面与模块

统一纸白/石墨/克制蓝；在线六图层与独立MVT实际加载。快照六步在backend/geoserver停止时仍可操作，B006详情正确；恢复状态另存recovered-service-state.json。故意改变容器快照analysis.json字节后哈希拒绝、三卡为空、Popup消失；恢复原字节后重试成功。模块快速切换清除旧会话，自动测试包含晚到/取消与Blob释放。390px CSS iframe检查保存图，未做手机硬件认证。

## 报告与视频

项目PDF8页、审查PDF5页；逐页文本非空，Poppler渲染13页并视觉检查，无溢出/乱码。架构与性能图直接绘制，图集来自同一科学源。可编辑Markdown随包。

最终视频210.933333秒、1280×800，288张实际截图，三个真实目标页，16段字幕；输出15fps重复帧、无音轨。最大样本间隔9.024秒，保留原时间，不加速。首版跨页目标错误经抽帧发现作废，修正后重录。证据video-validation.json、video-visual-check.md、video-frames.png和demo-capture.json。

## 交付与边界

源码由Git固定提交导出；科学包按manifest逐文件校验；快照包同源及逐文件SHA256。交付工具拒绝秘密路径、链接、穿越、坏哈希、缺交付物和覆盖已有输出；读取本机.env值只做内存泄漏扫描，不打印。最终包与SHA256核验另见release-manifest.json和发布结果。

负责人阶段2—6人工通过已记录；阶段7后授权进入交付但未提供CQL/MVT/投影/并发逐项人工签名，不补造。姓名/学号/班级、教师最终模板和截止日期仍待补。管理员数据库角色仅本机教学；基础展示完成，真实实时态势未接入、云弹性仅设计。最终独立审查记录见phase8-review.md（完成后写入）。

## 最终修复后的冻结核验

独立审查Critical0、Important2、Minor2；两个Important在实际App.vue回归测试先RED后GREEN后统一修复，不再派发复审。重新执行完整verify-final：后端119、前端39、QGIS32、交付6、guard3、负载契约3，共202项，9组PS契约与5条运行检查全部通过。完整原始输出随源码保留于docs/evidence/phase8/final-regression.txt。

最终从修复提交4a5eac4重新进行空源码/空库/新卷重建，项目ufw-rebuild-23c104c069c043149a5eac60c0ee39b1，11项核验成功，schema初始0，科学语义SHA不变，原容器身份不变，独立容器停止且卷保留。记录reconstruction-final.json和identity.json。之后仅添加交付文档与证据，不更改运行代码。

最终正式前端已从修复源码重建，浏览器在线与快照各六步（共12组合）均显示正确统计，记录final-browser.json；S02_T60为738775m²/91栋/14810m。最终截图final-runtime.png。演示录制在内部生命周期修复前，视觉及默认业务契约没有改变；修复后的12组合另行核验，不冒称重新录制。

延期小项及两项执行裁决完整记于phase8-review.md。源码发布提交由release-manifest.json准确固定；后续纯文档收尾提交不改变该固定源码。人工签字、个人信息与教师最终模板仍待负责人补充。
