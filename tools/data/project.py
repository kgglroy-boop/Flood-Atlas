"""QGIS styling and an atlas rendered from the actual scientific layers."""

import os
from pathlib import Path

from osgeo import gdal

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from qgis.PyQt.QtCore import QSize, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen, QLinearGradient
from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer, QgsRasterLayer,
                       QgsFillSymbol, QgsLineSymbol, QgsSingleSymbolRenderer,
                       QgsRasterShader, QgsColorRampShader, QgsSingleBandPseudoColorRenderer,
                       QgsRectangle, QgsMapSettings, QgsMapRendererParallelJob,
                       QgsProperty, QgsSymbolLayer)

_APP = None
PALETTE = [(0.101, '#d6eef0'), (.3, '#a8dce4'), (.6, '#69bfd0'),
           (1.0, '#3297b5'), (1.5, '#146a91'), (2.0, '#103f67')]


def application():
    global _APP
    # Review rendering must not append provider statistics sidecars to source TIFFs.
    gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
    if QgsApplication.instance() is None:
        _APP = QgsApplication([], False)
        _APP.initQgis()
    # Windows Qt's offscreen plugin starts with no system font families.
    if not QFontDatabase().families():
        font_root = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for name in ('msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf'):
            path = font_root / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        if not QFontDatabase().families():
            raise ValueError('QGIS offscreen renderer has no usable fonts.')
    return _APP


def _depth_layer(path: Path, label: str):
    layer = QgsRasterLayer(str(path), label)
    if not layer.isValid():
        raise ValueError('QGIS cannot open depth raster.')
    ramp = QgsColorRampShader(0, 2)
    ramp.setColorRampType(QgsColorRampShader.Interpolated)
    transparent = QColor(255, 255, 255, 0)
    items = [QgsColorRampShader.ColorRampItem(0, transparent, '干燥'),
             QgsColorRampShader.ColorRampItem(0.10000000149011612, transparent, '≤ 0.10 m')]
    items += [QgsColorRampShader.ColorRampItem(v, QColor(c), f'{v:g} m') for v, c in PALETTE]
    ramp.setColorRampItemList(items)
    shader = QgsRasterShader(0, 2)
    shader.setRasterShaderFunction(ramp)
    layer.setRenderer(QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader))
    return layer


def _vector(path: Path, name: str, label: str):
    layer = QgsVectorLayer(f'{path}|layername={name}', label, 'ogr')
    if not layer.isValid():
        raise ValueError(f'QGIS cannot open vector layer {name}.')
    return layer


def _styled_layers(dataset_dir):
    gpkg = dataset_dir / 'teaching.gpkg'
    study = _vector(gpkg, 'study_area', '研究区 · 2 km²')
    study.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
        'color': '#f5f8f8', 'outline_color': '#a8bcc2', 'outline_width': '0.24', 'outline_style': 'dash'})))
    buildings = _vector(gpkg, 'buildings', '建筑 · 200 栋')
    buildings.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
        'color': '255,255,255,105', 'outline_color': '#839ca8', 'outline_width': '0.17', 'joinstyle': 'round'})))
    roads = _vector(gpkg, 'roads', '道路 · 32 条中心线')
    line = QgsLineSymbol.createSimple({'line_color': '#bccad0', 'line_width': '0.20', 'capstyle': 'round'})
    line.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeWidth,
        QgsProperty.fromExpression('CASE WHEN "road_id" IN (\'RV10\',\'RH05\') THEN 0.45 ELSE 0.18 END'))
    roads.setRenderer(QgsSingleSymbolRenderer(line))
    depths = {(s, t): _depth_layer(dataset_dir / f'rasters/depth_{s}_T{t:02d}.tif',
                                  f'depth_{s}_T{t:02d} · 教学水深 m')
              for s in ('S01', 'S02') for t in (0, 30, 60)}
    return study, buildings, roads, depths


def write_qgis_project(dataset_dir: Path, contract: dict) -> Path:
    application()
    study, buildings, roads, depths = _styled_layers(dataset_dir)
    project = QgsProject()
    project.setTitle('虚构教学街区 | 城市内涝情景数据核查')
    project.setCrs(study.crs())
    project.setBackgroundColor(QColor('#f5f8f8'))
    root = project.layerTreeRoot()
    for layer in [study, *depths.values(), buildings, roads]:
        project.addMapLayer(layer, False)
    root.addLayer(roads)
    root.addLayer(buildings)
    group = root.addGroup('教学水深 · 两情景 × 三时间步')
    for key, layer in depths.items():
        node = group.addLayer(layer)
        node.setItemVisibilityChecked(key == ('S02', 60))
        node.setExpanded(False)
    extents = _vector(dataset_dir / 'teaching.gpkg', 'flood_extents', '淹没范围 · 6 步（T00 为空）')
    project.addMapLayer(extents, False)
    node = root.addLayer(extents)
    node.setItemVisibilityChecked(False)
    root.addLayer(study)
    from qgis.core import QgsReferencedRectangle
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(QgsRectangle(499950, 3399950, 502050, 3401050), study.crs()))
    path = dataset_dir / 'teaching-review.qgz'
    project.setFileName(str(path))
    if not project.write():
        raise ValueError('Could not write QGIS review project.')
    project.clear()
    return path


def write_atlas(dataset_dir: Path, report: dict) -> Path:
    application()
    study, buildings, roads, depths = _styled_layers(dataset_dir)
    image = QImage(1800, 1360, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('#f0f4f5'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    def text(x, y, value, size=20, color='#213d4a', bold=False):
        font = QFont('Microsoft YaHei')
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(int(x), int(y), value)

    text(64, 66, 'URBAN FLOOD / SYNTHETIC DATA ATLAS', 19, '#527985', True)
    text(64, 132, '虚构教学街区 · 内涝情景图集', 43, bold=True)
    text(64, 178, '2 km²  /  200 栋建筑  /  32 条道路  /  5 m 网格', 22, '#617b86')
    text(64, 218, '全部由确定性公式生成，用于 GIS 发布与空间分析教学。', 20, '#617b86')
    lookup = {(r['scenario_id'], r['time_min']): r for r in report['rasters']}
    for row, scenario in enumerate(('S01', 'S02')):
        for col, minute in enumerate((0, 30, 60)):
            x, y, w, h = 64 + col * 562, 260 + row * 446, 546, 418
            painter.setPen(QPen(QColor('#d9e3e7'), 1))
            painter.setBrush(QColor('#ffffff'))
            painter.drawRoundedRect(QRectF(x, y, w, h), 14, 14)
            text(x + 24, y + 42, f'{scenario}  /  教学情景{"A" if row == 0 else "B"}', 21, bold=True)
            text(x + w - 147, y + 42, f'{minute:02d} MIN', 24, '#227b93', True)
            settings = QgsMapSettings()
            settings.setLayers([roads, buildings, depths[(scenario, minute)], study])
            settings.setDestinationCrs(study.crs())
            settings.setBackgroundColor(QColor('#ffffff'))
            settings.setOutputSize(QSize(510, 264))
            settings.setExtent(QgsRectangle(499960, 3399960, 502040, 3401040))
            job = QgsMapRendererParallelJob(settings)
            job.start()
            job.waitForFinished()
            painter.drawImage(x + 18, y + 68, job.renderedImage())
            r = lookup[(scenario, minute)]
            text(x + 24, y + 361, f'淹没面积  {r["area_m2"] / 10000:,.2f} ha', 20, bold=True)
            text(x + 24, y + 393, '完全干燥 · 有效水深为 0' if minute == 0 else
                 f'最大水深  {r["max_depth_m"]:.3f} m  ·  湿像元 {r["wet_pixel_count"]:,}', 16, '#748b95')
    text(64, 1197, '水深 / m', 22, bold=True)
    gradient = QLinearGradient(260, 0, 1660, 0)
    for value, color in PALETTE:
        gradient.setColorAt(max(0, (value - .101) / (2 - .101)), QColor(color))
    painter.fillRect(QRectF(260, 1177, 1400, 20), gradient)
    for value in (.1, .3, .6, 1.0, 1.5, 2.0):
        x = 260 + (value - .1) / 1.9 * 1400
        text(x - 12, 1220, f'{value:.2f}', 16, '#52717f')
    text(64, 1256, 'EPSG:32650  ·  淹没阈值 > 0.10 m  ·  外围 NoData 不参与统计  ·  六图同尺度', 19, '#617b86')
    text(64, 1310, '教学合成数据  /  不代表真实灾情、降雨重现期或经过验证的水动力模拟', 20, '#9a694e')
    painter.end()
    path = dataset_dir / 'teaching-atlas.png'
    if not image.save(str(path)):
        raise ValueError('Could not write teaching atlas.')
    return path
