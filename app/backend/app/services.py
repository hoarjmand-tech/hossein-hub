import io,os,subprocess,tempfile,zipfile
from pathlib import Path
from PIL import Image
from pypdf import PdfReader
def extract_text(path:Path,mime:str|None):
 try:
  if mime=="application/pdf":
   text="\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
   if text.strip(): return text
   with tempfile.TemporaryDirectory() as td:
    subprocess.run(["pdftoppm","-f","1","-l","10","-jpeg","-r","180",str(path),f"{td}/p"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    out=[]
    for p in sorted(Path(td).glob("p-*.jpg")):
     out.append(subprocess.check_output(["tesseract",str(p),"stdout","-l","fas+eng+deu"],stderr=subprocess.DEVNULL,text=True))
    return "\n".join(out)
  if mime and mime.startswith("image/"):
   return subprocess.check_output(["tesseract",str(path),"stdout","-l","fas+eng+deu"],stderr=subprocess.DEVNULL,text=True)
 except Exception as e: return ""
 return ""
def thumbnail(path:Path,mime:str|None,out:Path):
 try:
  out.parent.mkdir(parents=True,exist_ok=True)
  if mime=="application/pdf":
   subprocess.run(["pdftoppm","-f","1","-singlefile","-jpeg","-scale-to","700",str(path),str(out.with_suffix(""))],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   jpg=out.with_suffix(".jpg")
   if jpg!=out: jpg.replace(out)
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
