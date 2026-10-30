
from PIL import Image
im = Image.open(r"C:\Users\nickd\Downloads\Project_AI\_glyph_view.png").convert("RGB")
w,h = im.size
print(w,h)
bg = im.getpixel((2,2))
print("bg", bg)
px = im.load()
for y in range(0,30):
    xs=[x for x in range(w) if px[x,y]!=bg]
    if xs: print(y, min(xs), max(xs), px[xs[0],y], px[xs[-1],y])
xs=[]; ys=[]
for y in range(0,70):
    for x in range(w-80,w):
        if px[x,y]!=bg: xs.append(x); ys.append(y)
print("topright bbox", (min(xs),min(ys),max(xs),max(ys)) if xs else None)
im.crop((0,0,w,40)).resize((w*4,160), Image.NEAREST).save(r"C:\Users\nickd\Downloads\Project_AI\_top_zoom.png")
im.crop((w-80,0,w,70)).resize((320,280), Image.NEAREST).save(r"C:\Users\nickd\Downloads\Project_AI\_tr_zoom.png")
