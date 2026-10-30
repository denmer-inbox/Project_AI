
from PIL import Image
im = Image.open(r"C:\Users\nickd\Downloads\Project_AI\_glyph_view.png").convert("RGB")
w,h=im.size; px=im.load(); bg=(6,23,34)
# find all text rows
rows=[]
for y in range(h):
    xs=[x for x in range(w) if px[x,y]!=bg]
    rows.append((y,len(xs),min(xs) if xs else -1,max(xs) if xs else -1))
for y,c,a,b in rows:
    if c: print(y,c,a,b)
