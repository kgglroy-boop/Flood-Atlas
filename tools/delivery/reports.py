"""Render two fixed, editable Chinese reports and an offline evidence index."""
import argparse
import html
import json
from pathlib import Path
import re
import shutil
import zipfile
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Flowable
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[2]

class EvidenceDiagram(Flowable):
 def __init__(self,kind):Flowable.__init__(self);self.kind=kind;self.width=475;self.height=150
 def draw(self):
  c=self.canv;c.setFont('YaHei',9)
  if self.kind=='architecture':
   boxes=[(0,95,130,'Vue / MapLibre'),(195,95,125,'GeoServer / GWC'),(195,22,100,'FastAPI'),(350,22,122,'PostGIS / 32650')]
   for x,y,w,label in boxes:
    c.setFillColor(colors.HexColor('#f7f7f3'));c.setStrokeColor(colors.HexColor('#dedfdb'));c.roundRect(x,y,w,42,10,fill=1,stroke=1);c.setFillColor(colors.HexColor('#24282c'));c.drawCentredString(x+w/2,y+17,label)
   c.setStrokeColor(colors.HexColor('#62676d'));c.line(130,115,195,115);c.line(65,95,65,42);c.line(65,42,195,42);c.line(295,42,350,42)
   c.setFillColor(colors.HexColor('#62676d'));c.setFont('YaHei',8);c.drawString(141,122,'WMTS');c.drawString(87,48,'/api');c.drawString(305,48,'SQL')
  else:
   c.setFillColor(colors.HexColor('#24282c'));c.drawString(0,132,'固定本机样本 / 20VU p95 与GWC中位数（ms）')
   from tools.delivery.evidence import load_facts
   facts=load_facts()
   for i,(label,value) in enumerate([('GWC cold',facts['cold']),('GWC hot',facts['hot']),('health p95',facts['health_p95']),('summary p95',facts['summary_p95'])]):
    y=100-i*27;c.setFillColor(colors.HexColor('#62676d'));c.drawString(0,y,label);c.setFillColor(colors.HexColor('#245b7c'));c.roundRect(105,y-2,value/facts['cold']*285,9,3,fill=1,stroke=0);c.drawString(402,y,f'{value:.2f}')

def render_report(source,output,assets,expected):
 pdfmetrics.registerFont(TTFont('YaHei','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
 pdfmetrics.registerFont(TTFont('YaHeiBold','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
 body=ParagraphStyle('body',fontName='YaHei',fontSize=11.2,leading=20,textColor=colors.HexColor('#24282c'),wordWrap='CJK',spaceAfter=14)
 title=ParagraphStyle('title',parent=body,fontName='YaHeiBold',fontSize=23,leading=32,spaceAfter=24,textColor=colors.HexColor('#24282c'))
 story=[]
 for page_index,section in enumerate(source.read_text(encoding='utf-8').split('---PAGE---')):
  if page_index:story.append(PageBreak())
  story.append(Spacer(1,17))
  for block in re.split(r'\n\s*\n',section.strip()):
   if block.startswith('# '):
    heading,_,remaining=block.partition('\n')
    story.append(Paragraph(html.escape(heading[2:]),title))
    if remaining.strip():story.append(Paragraph(html.escape(remaining).replace('\n','<br/>'),body))
    continue
   match=re.fullmatch(r'!\[(.*?)\]\((.*?)\)',block.strip())
   if match:
    im=Image(str(assets/match[2]));ratio=im.imageHeight/im.imageWidth
    width=475; height=width*ratio
    if height>365:width*=365/height;height=365
    im.drawWidth=width;im.drawHeight=height;story.extend([Spacer(1,8),im,Spacer(1,15)]);continue
   story.append(Paragraph(html.escape(block).replace('\n','<br/>'),body))
  if '# 02 / 架构' in section:story.extend([Spacer(1,14),EvidenceDiagram('architecture')])
  if '# 03 / GWC' in section:story.extend([Spacer(1,14),EvidenceDiagram('performance')])
 def chrome(c,doc):
  w,h=A4;c.setFillColor(colors.HexColor('#62676d'));c.setFont('YaHei',8)
  c.drawString(54,h-33,'FLOOD ATLAS   /   URBAN WEBGIS')
  c.setStrokeColor(colors.HexColor('#dedfdb'));c.line(54,h-43,w-54,h-43);c.line(54,43,w-54,43)
  c.drawString(54,28,'教学合成数据 · 本地实测 · 2026.10.20');c.drawRightString(w-54,28,f'{doc.page:02d} / {expected:02d}')
 doc=SimpleDocTemplate(str(output),pagesize=A4,rightMargin=54,leftMargin=54,topMargin=62,bottomMargin=62,title=source.stem,author='Urban Flood WebGIS course project')
 doc.build(story,onFirstPage=chrome,onLaterPages=chrome)
 reader=PdfReader(output)
 if len(reader.pages)!=expected:raise ValueError(f'{source.stem}: expected {expected} pages, got {len(reader.pages)}')
 if any(len(p.extract_text().strip())<70 for p in reader.pages):raise ValueError('Blank report page')
 return dict(name=output.name,pages=expected,text_checked=True)

def prepare(output, visual=None):
 output.mkdir(parents=True,exist_ok=True)
 visual=visual or ROOT/'docs/evidence/phase8/visual'
 for src,dst in [('main-final.png','frontend-main.png'),('mobile-final.png','frontend-mobile.png'),('mvt-final.png','frontend-mvt.png')]:shutil.copyfile(visual/src,output/dst)
 for name in ['project-report.md','engineering-report.md','architecture.md','manual-review.md','assessment-matrix.md']:
  text=(ROOT/'docs/delivery'/name).read_text(encoding='utf-8').replace('docs/image-lock.md','docs/image-lock.json')
  (output/name).write_text(text,encoding='utf-8')
 shutil.copyfile(ROOT/'docs/ai-log.csv',output/'ai-collaboration-log.csv')
 shutil.copyfile(ROOT/'design/tokens.json',output/'design-tokens.json')
 shutil.copyfile(ROOT/'docs/map-data-modules.md',output/'module-guide.md')
 with zipfile.ZipFile(output/'map-module.zip','w',zipfile.ZIP_DEFLATED) as z:
  directory=ROOT/'frontend/public/maps/teaching-snapshot'
  manifest=json.loads((directory/'module.json').read_text(encoding='utf-8'))
  from tools.delivery.bundle import hash_file
  for name,digest in manifest['files'].items():
   if hash_file(directory/name)!=digest:raise ValueError('Module changed')
  for name in ['module.json',*manifest['files']]:z.write(directory/name,'maps/teaching-snapshot/'+name)
 results=[render_report(output/'project-report.md',output/'project-report.pdf',output,8),render_report(output/'engineering-report.md',output/'engineering-report.pdf',output,5)]
 from tools.delivery.evidence import render
 render(output)
 (output/'reports-validation.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
 return results

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--visual-root',type=Path);a=p.parse_args();print(json.dumps(prepare(a.output,a.visual_root)))
