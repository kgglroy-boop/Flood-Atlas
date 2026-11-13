"""Encode actual timestamped browser samples without speeding up the demonstration."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import textwrap
from PIL import Image,ImageOps

def stamp(seconds):
 ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
 return f'{h:02}:{m:02}:{s:02},{ms:03}'

def validate_views(rows):
 if not {'main','mvt','evidence'}.issubset({row.get('view') for row in rows}):raise ValueError('Required demonstration views absent')

def encode(artifacts,frames):
 capture=json.loads((artifacts/'demo-capture.json').read_text(encoding='utf-8'))
 duration=capture['duration_seconds'];rows=capture['frames'];events=capture['events']
 validate_views(rows)
 if not 180<=duration<=300 or len(rows)<180:raise ValueError('Insufficient actual recording')
 previous=-1;gaps=[];concat=[]
 normalized=frames/'normalized';normalized.mkdir(exist_ok=True)
 for i,row in enumerate(rows):
  name=row['file'];at=row['at'];end=rows[i+1]['at'] if i+1<len(rows) else duration
  if not re.fullmatch(r'\d{5}\.png',name) or at<=previous or not end>at:raise ValueError('Invalid frame timeline')
  previous=at;gaps.append(end-at)
  im=ImageOps.contain(Image.open(frames/name).convert('RGB'),(1280,720));canvas=Image.new('RGB',(1280,720),'#f7f7f3');canvas.paste(im,((1280-im.width)//2,0));canvas.save(normalized/name)
  concat.extend([f"file '{(normalized/name).resolve().as_posix()}'",f'duration {end-at:.6f}'])
 concat.append(f"file '{(normalized/rows[-1]['file']).resolve().as_posix()}'")
 (frames/'concat.txt').write_text('\n'.join(concat),encoding='utf-8')
 subtitles=[]
 for i,event in enumerate(events):
  end=events[i+1]['at'] if i+1<len(events) else duration
  subtitles.append(f"{i+1}\n{stamp(event['at'])} --> {stamp(end)}\n"+'\n'.join(textwrap.wrap(event['text'],44))+'\n')
 (artifacts/'demo.srt').write_text('\n'.join(subtitles),encoding='utf-8')
 subtitle=(artifacts/'demo.srt').as_posix()
 if Path(subtitle).is_absolute():raise ValueError('Run encoder using repository-relative artifact directory')
 vf=f"fps=15,pad=1280:800:0:0:white,subtitles={subtitle}:force_style='FontName=Microsoft YaHei,FontSize=11,PrimaryColour=&H002C2824,Outline=0,Shadow=0,MarginV=5,Alignment=2'"
 command=['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','concat','-safe','0','-i',str(frames/'concat.txt'),'-vf',vf,'-t',str(duration),'-c:v','libx264','-preset','medium','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(artifacts/'demo.mp4')]
 subprocess.run(command,check=True)
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(artifacts/'demo.mp4')],text=True))
 if abs(float(probe['format']['duration'])-duration)>1 or probe['streams'][0]['width']!=1280 or probe['streams'][0]['height']!=800:raise ValueError('Encoded duration/dimensions differ')
 report={'status':'ok','duration_seconds':float(probe['format']['duration']),'actual_samples':len(rows),'max_sample_gap_seconds':max(gaps),'video_fps':'15; repeated real samples, not native15fps recording','width':1280,'height':800,'audio':False,'subtitles':'burned in and separate SRT','events':len(events)}
 (artifacts/'video-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 return report

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--frames',type=Path,required=True);a=p.parse_args();print(json.dumps(encode(a.artifacts,a.frames)))
