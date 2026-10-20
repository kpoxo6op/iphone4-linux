#!/usr/bin/env python3
"""Bake licensed DejaVu Sans Mono glyph masks; runtime has no font dependency."""
from pathlib import Path
import struct,hashlib,json
from PIL import Image,ImageFont,ImageDraw
root=Path(__file__).resolve().parents[1]
font=Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf')
codes=sorted(set(range(32,127))|set(range(160,256))|set(range(0x400,0x500))|set(range(0x2500,0x25a0))|set(range(0x2190,0x2195))|{0x2013,0x2014,0x2018,0x2019,0x201c,0x201d,0x2022,0x2026,0x2039,0x203a,0x2212,0x20ac})
manifest={'source':'https://dejavu-fonts.github.io/','font_sha256':hashlib.sha256(font.read_bytes()).hexdigest(),'generator':'Pillow FreeType rasterization, fixed baseline, alpha masks','fonts':{}}
for size in (24,36,48,96):
 f=ImageFont.truetype(str(font),size); ascent,descent=f.getmetrics();w=round(f.getlength('M'));h=ascent+descent+4
 chosen=codes if size!=96 else sorted(set(range(32,127))|{0x2014})
 data=bytearray(struct.pack('<4I',0x31594f53,w,h,len(chosen)))
 for c in chosen:
  im=Image.new('L',(w,h));ImageDraw.Draw(im).text((0,ascent),chr(c),font=f,fill=255,anchor='ls')
  data+=struct.pack('<I',c)+im.tobytes()
 p=root/'assets'/f'mono-{size}.soyfont';p.write_bytes(data)
 manifest['fonts'][str(size)]={'cell':[w,h],'glyphs':len(chosen),'sha256':hashlib.sha256(data).hexdigest()}
(root/'assets/fonts.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Baked four Latin/Cyrillic/terminal glyph atlases.')
