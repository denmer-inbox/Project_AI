
from PIL import Image
im = Image.open(r"C:\Users\nickd\Downloads\Project_AI\_top_view.png").convert("RGB")
w,h = im.size
print("size", w, h)
print("bg", im.getpixel((100,6)), im.getpixel((10,120)), im.getpixel((200,250)))
for y in range(h):
    cnt = sum(1 for x in range(w) if sum(im.getpixel((x,y)))>200)
    if cnt>3:
        print("first bright row", y, cnt); break
pts=[(x,y,im.getpixel((x,y))) for y in range(15) for x in range(w) if (lambda p: p[1]>100 and p[1]>p[0]+40 and p[1]>p[2]+40)(im.getpixel((x,y)))]
print("green pts top count", len(pts))
if pts:
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    print("dot bbox x",min(xs),max(xs),"y",min(ys),max(ys))
    cx=(min(xs)+max(xs))//2; cy=(min(ys)+max(ys))//2
    print("dot center color", im.getpixel((cx,cy)))
runs=[];run=None
for y in range(h):
    cnt=sum(1 for x in range(w) if sum(im.getpixel((x,y)))>60)
    if cnt<=2:
        run=[y] if run is None else run
    else:
        if run is not None: runs.append((run[0],y-1)); run=None
if run: runs.append((run[0],h-1))
print("empty runs:", [r for r in runs if r[1]-r[0]>1])
for y in range(h-1,0,-1):
    cnt=sum(1 for x in range(w) if sum(im.getpixel((x,y)))>200)
    if cnt>3: print("last bright row", y, cnt); break
