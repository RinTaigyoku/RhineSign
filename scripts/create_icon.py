"""Export project artwork to Windows and high-DPI application icon sizes."""
from pathlib import Path
from PIL import Image
r=Path(__file__).resolve().parents[1]/'assets'
master=Image.open(r/'icon-master.png').convert('RGBA')
sizes=(16,20,24,32,40,48,64,128,256,512)
images={s:master.resize((s,s),Image.Resampling.LANCZOS)for s in sizes}
for size,image in images.items():image.save(r/f'icon-{size}.png')
images[512].save(r/'icon.png')
images[512].save(r/'icon.ico',sizes=[(s,s)for s in sizes if s<=256],append_images=[images[s]for s in sizes if s<=256])
print('Windows icon sizes exported.')
