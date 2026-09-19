import subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageEnhance,ImageFilter,ImageOps

def preprocess_image(src:Path,dst:Path):
 im=Image.open(src).convert("L")
 im=ImageOps.autocontrast(im)
 if max(im.size)<1800:
  s=1800/max(im.size); im=im.resize((int(im.width*s),int(im.height*s)))
 im=ImageEnhance.Contrast(im).enhance(1.35)
 im=im.filter(ImageFilter.SHARPEN)
 im.save(dst,"PNG")
 return dst

def enhanced_tesseract(src:Path):
 with tempfile.TemporaryDirectory() as td:
  p=Path(td)/"page.png"; preprocess_image(src,p)
  best=""
  for psm in ("6","11","3"):
   try:
    x=subprocess.check_output(["tesseract",str(p),"stdout","-l","fas+eng+deu","--psm",psm],stderr=subprocess.DEVNULL,text=True,timeout=120)
    if len(x.strip())>len(best.strip()):best=x
   except Exception:pass
  return best
