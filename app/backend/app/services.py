import subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageEnhance,ImageOps
from pypdf import PdfReader

def _prep(src:Path,dst:Path):
 im=Image.open(src).convert("L")
 im=ImageOps.autocontrast(im)
 if max(im.size)<1800:
  s=1800/max(im.size);im=im.resize((int(im.width*s),int(im.height*s)))
 im=ImageEnhance.Contrast(im).enhance(1.25)
 im.save(dst,"PNG")

def _tess(path:Path):
 try:
  return subprocess.check_output(["tesseract",str(path),"stdout","-l","fas+eng+deu","--psm","6"],stderr=subprocess.DEVNULL,text=True,timeout=60)
 except Exception:return ""

def extract_text(path:Path,mime:str|None):
 try:
  if mime=="application/pdf":
   native="\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
   if len(native.strip())>=80:return native
   with tempfile.TemporaryDirectory() as td:
    subprocess.run(["pdftoppm","-f","1","-l","5","-png","-r","160",str(path),f"{td}/p"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90)
    return "\n".join(_tess(p) for p in sorted(Path(td).glob("p-*.png")))
  if mime and mime.startswith("image/"):
   with tempfile.TemporaryDirectory() as td:
    p=Path(td)/"ocr.png";_prep(path,p);return _tess(p)
 except Exception:return ""
 return ""

def thumbnail(path:Path,mime:str|None,out:Path):
 try:
  out.parent.mkdir(parents=True,exist_ok=True)
  if mime=="application/pdf":
   subprocess.run(["pdftoppm","-f","1","-singlefile","-jpeg","-scale-to","700",str(path),str(out.with_suffix(""))],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
   jpg=out.with_suffix(".jpg")
   if jpg!=out and jpg.exists():jpg.replace(out)
  elif mime and mime.startswith("image/"):
   im=Image.open(path);im.thumbnail((700,700));im.convert("RGB").save(out,"JPEG",quality=82)
  return out.exists()
 except Exception:return False

def safe_name(s:str)->str:
 import re
 s=Path(s or "file").name
 return re.sub(r'[^\w.()\- \u0600-\u06ff]+','_',s)[:180] or "file"

def detected_mime(path:Path)->str:
 try:
  import magic
  return magic.from_file(str(path),mime=True) or "application/octet-stream"
 except Exception:return "application/octet-stream"
