#!/usr/bin/env python3
"""Bake licensed DejaVu Sans Mono glyph masks; runtime has no font dependency."""
from pathlib import Path
import struct,hashlib,json
from PIL import Image,ImageFont,ImageDraw
root=Path(__file__).resolve().parents[1]
font=Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf')
codes=sorted(set(range(32,127))|set(range(160,256))|set(range(0x400,0x500))|set(range(0x2500,0x25a0))|set(range(0x2190,0x2195))|{0x2013,0x2014,0x2018,0x2019,0x201c,0x201d,0x2022,0x2026,0x2039,0x203a,0x2212,0x20ac})
manifest={'source':'https://dejavu-fonts.github.io/','font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),'generator':'Pillow FreeType rasterization, fixed baseline, alpha masks; box drawing stretched and block elements drawn to fill the cell','fonts':{}}
QUADS={0x2596:4,0x2597:8,0x2598:1,0x2599:13,0x259a:9,0x259b:7,0x259c:11,0x259d:2,0x259e:6,0x259f:14}
def block(c,w,h):
 # Block elements fill the whole cell, as terminals draw them, so tiles join
 # with their neighbours on every side: maps and bars have no seams.
 im=Image.new('L',(w,h));d=ImageDraw.Draw(im);hw,hh=w//2,h//2
 def box(x0,y0,x1,y1):
  if x1>x0 and y1>y0:d.rectangle((x0,y0,x1-1,y1-1),fill=255)
 if c==0x2580:box(0,0,w,hh)
 elif 0x2581<=c<=0x2588:box(0,h-round(h*(c-0x2580)/8),w,h)
 elif 0x2589<=c<=0x258f:box(0,0,round(w*(0x2590-c)/8),h)
 elif c==0x2590:box(hw,0,w,h)
 elif c==0x2594:box(0,0,w,round(h/8))
 elif c==0x2595:box(w-round(w/8),0,w,h)
 elif c in (0x2591,0x2592,0x2593):
  on={0x2591:lambda x,y:x%2==0 and y%2==0,0x2592:lambda x,y:(x+y)%2==0,0x2593:lambda x,y:not(x%2 and y%2)}[c]
  for y in range(h):
   for x in range(w):
    if on(x,y):im.putpixel((x,y),255)
 else:
  q=QUADS[c]
  if q&1:box(0,0,hw,hh)
  if q&2:box(hw,0,w,hh)
  if q&4:box(0,hh,hw,h)
  if q&8:box(hw,hh,w,h)
 return im
for size in (24,32,36,42,48,54,96):
 f=ImageFont.truetype(str(font),size); ascent,descent=f.getmetrics();w=round(f.getlength('M'));h=ascent+descent+4
 chosen=codes if size!=96 else sorted(set(range(32,127))|{0x2014})
 data=bytearray(struct.pack('<4I',0x31594f53,w,h,len(chosen)))
 for c in chosen:
  if 0x2580<=c<0x25a0:im=block(c,w,h)
  else:
   im=Image.new('L',(w,h));ImageDraw.Draw(im).text((0,ascent),chr(c),font=f,fill=255,anchor='ls')
   # Box drawing spans ascent to descent; stretch it over the line gap too so
   # lines in neighbouring rows meet.
   if 0x2500<=c<0x2580:im=im.crop((0,0,w,ascent+descent)).resize((w,h),Image.BILINEAR)
  data+=struct.pack('<I',c)+im.tobytes()
 p=root/'assets'/f'mono-{size}.soyfont';p.write_bytes(data)
 manifest['fonts'][str(size)]={'cell':[w,h],'glyphs':len(chosen),'sha256':hashlib.sha256(data).hexdigest()}
(root/'assets/fonts.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Baked Latin/Cyrillic/terminal glyph atlases.')
