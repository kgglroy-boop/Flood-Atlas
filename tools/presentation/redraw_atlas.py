"""Redraw display panels only; never change scientific rasters or geometries.

Run with QGIS Python from the repository root. Output is a candidate PNG; publishing
and updating its one manifest checksum are separate, verified operations.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from osgeo import gdal
gdal.UseExceptions()
from tools.data.project import application, _styled_layers
from qgis.PyQt.QtCore import QSize, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter
from qgis.core import (QgsRasterLayer, QgsFillSymbol, QgsLineSymbol,
                       QgsSingleSymbolRenderer, QgsSimpleLineSymbolLayer,
                       QgsMapSettings, QgsMapRendererParallelJob, QgsRectangle,
                       QgsProperty, QgsSymbolLayer)


def redraw(dataset: Path, imagery: Path, metadata: Path, output: Path):
    application()
    provenance = json.loads(metadata.read_text(encoding='utf-8-sig'))
    extent = provenance['extent']
    assert extent == [499960, 3399960, 502040, 3401040]
    assert provenance['epsg'] == 32650
    georeferenced = imagery.with_name('world-imagery-georeferenced.tif')
    translated = gdal.Translate(str(georeferenced), str(imagery),
        outputSRS='EPSG:32650', outputBounds=[extent[0], extent[3], extent[2], extent[1]],
        creationOptions=['COMPRESS=DEFLATE', 'TILED=YES'])
    translated.Close()
    basemap = QgsRasterLayer(str(georeferenced), '实景背景（仅展示）')
    if not basemap.isValid():
        raise ValueError('Cannot open georeferenced display imagery.')
    basemap.setOpacity(.28)
    study, buildings, roads, depths = _styled_layers(dataset)
    study.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
        'color': '255,255,255,0', 'outline_color': '#a3b3aa',
        'outline_width': '0.22', 'outline_style': 'dash'})))
    buildings.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
        'color': '255,252,240,165', 'outline_color': '#637f85',
        'outline_width': '0.18', 'joinstyle': 'miter'})))
    symbol = QgsLineSymbol.createSimple({'line_color': '#7f8e86', 'line_width': '0.42'})
    symbol.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeWidth,
        QgsProperty.fromExpression('CASE WHEN "road_id" IN (\'RV10\',\'RH05\') THEN 0.72 ELSE 0.30 END'))
    inner = QgsSimpleLineSymbolLayer.create({'line_color': '#f8f5e9', 'line_width': '0.20'})
    inner.setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeWidth,
        QgsProperty.fromExpression('CASE WHEN "road_id" IN (\'RV10\',\'RH05\') THEN 0.48 ELSE 0.16 END'))
    symbol.appendSymbolLayer(inner)
    roads.setRenderer(QgsSingleSymbolRenderer(symbol))
    original = QImage(str(dataset / 'teaching-atlas.png'))
    if original.isNull() or original.size() != QSize(1800, 1360):
        raise ValueError('Original atlas dimensions differ.')
    result = original.copy()
    painter = QPainter(result)
    for row, scenario in enumerate(('S01', 'S02')):
        for column, minute in enumerate((0, 30, 60)):
            x, y = 82 + column * 562, 328 + row * 446
            settings = QgsMapSettings()
            settings.setLayers([roads, buildings, depths[(scenario, minute)], study, basemap])
            settings.setDestinationCrs(study.crs())
            settings.setBackgroundColor(QColor('#eff2eb'))
            settings.setOutputSize(QSize(510, 264))
            settings.setExtent(QgsRectangle(*extent))
            job = QgsMapRendererParallelJob(settings)
            job.start()
            job.waitForFinished()
            panel = job.renderedImage()
            if panel.isNull():
                raise ValueError('Map rendering failed.')
            credits = QPainter(panel)
            credits.fillRect(QRectF(0, 240, 510, 24), QColor(255, 255, 255, 225))
            font = QFont('Microsoft YaHei')
            font.setPixelSize(10)
            credits.setFont(font)
            credits.setPen(QColor('#36505a'))
            credits.drawText(6, 250, '实景底图 + 虚构教学叠加（非真实洪涝）')
            font.setPixelSize(9)
            credits.setFont(font)
            credits.drawText(6, 261, 'Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community')
            credits.end()
            painter.drawImage(x, y, panel)
    painter.end()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not result.save(str(output)):
        raise ValueError('Could not write redrawn atlas.')
    print(json.dumps({'status': 'ok', 'output': str(output), 'width': 1800, 'height': 1360,
                      'scope': 'six display panels only; original data and outside pixels unchanged'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', type=Path, required=True)
    parser.add_argument('--imagery', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    redraw(args.dataset_dir, args.imagery, args.metadata, args.output)
