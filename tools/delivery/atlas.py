"""A final paper/graphite atlas drawn from the unchanged scientific layers."""
import argparse
import json
from pathlib import Path
from qgis.PyQt.QtCore import QSize,QRectF,Qt
from qgis.PyQt.QtGui import QImage,QPainter,QColor,QFont,QPen,QLinearGradient
from qgis.core import QgsVectorLayer,QgsFillSymbol,QgsLineSymbol,QgsSingleSymbolRenderer,QgsProperty,QgsSymbolLayer,QgsMapSettings,QgsMapRendererParallelJob,QgsRectangle
from tools.data.project import application,_depth_layer
from tools.analysis.reference import calculate_reference
from tools.data.integrity import file_sha

def draw_atlas(dataset:Path,output:Path):
 application();before=file_sha(dataset/'manifest.json');reference=calculate_reference(dataset/'teaching.gpkg')
 study=QgsVectorLayer(f'{dataset}/teaching.gpkg|layername=study_area','Study','ogr')
 buildings=QgsVectorLayer(f'{dataset}/teaching.gpkg|layername=buildings','Buildings','ogr')
 roads=QgsVectorLayer(f'{dataset}/teaching.gpkg|layername=roads','Roads','ogr')
 study.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'color':'#fcfcfd','outline_color':'#afb6c0','outline_style':'dash','outline_width':'.17'})))
 roads.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({'line_color':'#d4d9e0','line_width':'.10'})))
 image=QImage(1800,1360,QImage.Format_ARGB32);image.fill(QColor('#f7f7f3'));p=QPainter(image);p.setRenderHint(QPainter.Antialiasing)
 def text(x,y,value,size=16,color='#62676d',bold=False):
  font=QFont('Microsoft YaHei');font.setPixelSize(size);font.setBold(bold);p.setFont(font);p.setPen(QColor(color));p.drawText(x,y,value)
 text(82,76,'FLOOD ATLAS / DATA STUDIES',16)
 text(82,143,'城市内涝教学情景',48,'#24282c',True)
 text(83,191,'两个情景，三个时间步。以统一比例观察街区水深与空间影响。',20)
 text(83,240,'虚构街区 2 km × 1 km    /    EPSG:32650    /    5 m 网格    /    淹没阈值 > 0.10 m',16)
 for row,scenario in enumerate(('S01','S02')):
  for column,minute in enumerate((0,30,60)):
   step=f'{scenario}_T{minute:02}';r=next(s for s in reference['steps'] if s['step_id']==step)
   x,y=72+column*562,290+row*455
   p.setPen(Qt.NoPen);p.setBrush(QColor('#ffffff'));p.drawRoundedRect(QRectF(x,y,532,420),20,20)
   text(x+22,y+42,f'情景 {"A" if scenario=="S01" else "B"}  /  {minute:02} 分钟',20,'#24282c',True)
   text(x+22,y+72,step,12,'#62676d')
   affected=','.join("'"+v+"'" for v in r['affected_building_ids']) or "''"
   fill=QgsFillSymbol.createSimple({'color':'#fcfcfd','outline_color':'#a0a6ae','outline_width':'.14'})
   fill.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.PropertyFillColor,QgsProperty.fromExpression(f'CASE WHEN "building_id" IN ({affected}) THEN \'#66717e\' ELSE \'#fcfcfd\' END'))
   fill.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeColor,QgsProperty.fromExpression(f'CASE WHEN "building_id" IN ({affected}) THEN \'#343e4a\' ELSE \'#a0a6ae\' END'))
   buildings.setRenderer(QgsSingleSymbolRenderer(fill))
   depth=_depth_layer(dataset/f'rasters/depth_{step}.tif',step)
   settings=QgsMapSettings();settings.setLayers([buildings,roads,depth,study]);settings.setDestinationCrs(study.crs());settings.setBackgroundColor(QColor('#fcfcfd'));settings.setOutputSize(QSize(488,253));settings.setExtent(QgsRectangle(499960,3399960,502040,3401040))
   job=QgsMapRendererParallelJob(settings);job.start();job.waitForFinished();p.drawImage(x+22,y+91,job.renderedImage())
   text(x+22,y+377,f'{r["flooded_area_m2"]:,.0f} m²     {len(r["affected_building_ids"])} 栋     {r["flooded_road_length_m"]:,.0f} m',16,'#62676d')
 text(83,1215,'水深 / m',14)
 from tools.data.project import PALETTE
 gradient=QLinearGradient(83,0,523,0);gradient.setColorAt(0,QColor(PALETTE[0][1]))
 for value,color in PALETTE:gradient.setColorAt((value-.1)/1.9,QColor(color))
 p.fillRect(QRectF(83,1235,440,8),gradient)
 for value in (.1,.3,.6,1,1.5,2):text(int(83+(value-.1)/1.9*440)-(0 if value==.1 else 13),1266,f'{value:.2f}',12)
 text(570,1245,'≤ 0.10 m 与 NoData 透明显示',14)
 text(83,1318,'预计算教学合成数据，不代表真实灾情或经过验证的洪涝风险预测。',15)
 text(1270,1318,'FLOOD ATLAS  /  2026',14,'#62676d');p.end()
 output.parent.mkdir(parents=True,exist_ok=True)
 if not image.save(str(output)):raise ValueError('Final atlas write failed')
 if file_sha(dataset/'manifest.json')!=before:raise ValueError('Source manifest changed')
 return dict(status='ok',output=str(output.resolve()),width=1800,height=1360,source_manifest_unchanged=True)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--dataset',type=Path,required=True);a.add_argument('--output',type=Path,required=True);v=a.parse_args();print(json.dumps(draw_atlas(v.dataset,v.output)))
