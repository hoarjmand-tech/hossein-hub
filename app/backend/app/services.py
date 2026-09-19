import re,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageEnhance,ImageFilter,ImageOps
from pypdf import PdfReader

PERSIAN_RE=re.compile(r"[\u0600-\u06FF]")
LATIN_RE=re.compile(r"[A-Za-z]")

def _prep(src:Path,dst:Path,threshold=False):
 im=Image.open(src).convert("L")
 im=ImageOps.autocontrast(im)
 if max(im.size)<2200:
  s=2200/max(im.size)
  im=im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))))
 im=ImageEnhance.Contrast(im).enhance(1.35)
 im=im.filter(ImageFilter.SHARPEN)
 if threshold: im=im.point(lambda x:255 if x>170 else 0)
 im.save(dst,"PNG")

def _quality(text:str)->float:
 t=(text or "").strip()
 if not t:return -9999
 chars=[c for c in t if not c.isspace()]
 letters=sum(c.isalpha() for c in chars)
 persian=len(PERSIAN_RE.findall(t))
 latin=len(LATIN_RE.findall(t))
 digits=sum(c.isdigit() for c in chars)
 words=re.findall(r"[\w\u0600-\u06FF]{2,}",t,re.UNICODE)
 weird=sum(not (c.isalnum() or c.isspace() or c in ".,:;،؛؟!?()[]{}%/\\-+_@#&'\"") for c in t)
 common=["ایران","جمهوری","وزارت","شرکت","شماره","تاریخ","نام","نشانی","قرارداد","نامه","بیمه","دانشگاه","österreich","wien","vertrag","bescheid","rechnung","versicherung","passport","university","bank","invoice"]
 keyword=sum(1 for k in common if k.lower() in t.lower())
 return letters*.8+len(words)*2.5+persian*1.8+latin*.25+digits*.15+keyword*20-weird*4

def _tess(path:Path,langs:str,psm:int)->str:
 try:
  return subprocess.check_output(["tesseract",str(path),"stdout","-l",langs,"--oem","1","--psm",str(psm),"-c","preserve_interword_spaces=1"],stderr=subprocess.DEVNULL,text=True,timeout=90)
 except Exception:return ""

def _ocr_image(src:Path)->str:
 with tempfile.TemporaryDirectory() as td:
  td=Path(td);normal=td/"normal.png";binary=td/"binary.png"
  _prep(src,normal,False);_prep(src,binary,True)
  candidates=[
   _tess(normal,"fas+eng+deu",6),
   _tess(normal,"fas+eng+deu",11),
   _tess(binary,"fas+eng",6),
   _tess(binary,"fas+eng",11),
  ]
  return max(candidates,key=_quality,default="")

def _native_text_ok(text:str)->bool:
 t=(text or "").strip()
 if len(t)<120:return False
 letters=sum(c.isalpha() for c in t)
 words=len(re.findall(r"[\w\u0600-\u06FF]{2,}",t,re.UNICODE))
 return letters>=60 and words>=18 and _quality(t)>=120

def extract_text(path:Path,mime:str|None):
 try:
  if mime=="application/pdf":
   native="\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages[:10])
   if _native_text_ok(native):return native
   with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    subprocess.run(["pdftoppm","-f","1","-l","6","-png","-r","220",str(path),str(td/"page")],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
    ocr="\n".join(_ocr_image(p) for p in sorted(td.glob("page-*.png")))
    return ocr if _quality(ocr)>=_quality(native) else native
  if mime and mime.startswith("image/"):return _ocr_image(path)
 except Exception as e:
  print("ocr-extract:",path.name,e,flush=True)
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
 s=Path(s or "file").name
 return re.sub(r'[^\w.()\- \u0600-\u06ff]+','_',s)[:180] or "file"

def detected_mime(path:Path)->str:
 try:
  import magic
  return magic.from_file(str(path),mime=True) or "application/octet-stream"
 except Exception:return "application/octet-stream"
