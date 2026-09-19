import re,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageEnhance,ImageFilter,ImageOps
from pypdf import PdfReader

PERSIAN_RE=re.compile(r"[\u0600-\u06FF]")
LATIN_RE=re.compile(r"[A-Za-z]")
WORD_RE=re.compile(r"[A-Za-z0-9\u0600-\u06FF][A-Za-z0-9\u0600-\u06FF._\-/]{1,}",re.UNICODE)

PERSIAN_COMMON={
 "ایران","اسلامی","جمهوری","وزارت","شرکت","شماره","تاریخ","نام","نام خانوادگی","نشانی","قرارداد","نامه","بیمه",
 "دانشگاه","مدرک","گواهی","اداره","دادگاه","بانک","حساب","مبلغ","ریال","تومان","کد","ملی","شناسنامه","گذرنامه",
 "استان","شهرستان","تهران","درخواست","موضوع","پیوست","محترم","مدیر","مدیریت","کارشناس","تایید","تأیید","صادر"
}
LATIN_COMMON={
 "passport","republic","iran","name","surname","date","number","invoice","bank","statement","university","certificate",
 "austria","österreich","wien","vertrag","bescheid","versicherung","rechnung","magistrat","address","account","document"
}

def _prep(src:Path,dst:Path,threshold=False):
 im=Image.open(src).convert("L")
 im=ImageOps.autocontrast(im)
 if max(im.size)<2600:
  s=2600/max(im.size)
  im=im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))))
 im=ImageEnhance.Contrast(im).enhance(1.45)
 im=im.filter(ImageFilter.SHARPEN)
 if threshold:
  im=im.point(lambda x:255 if x>175 else 0)
 im.save(dst,"PNG")

def _parse_tsv(raw:str):
 rows=[]
 for i,line in enumerate((raw or "").splitlines()):
  if i==0:continue
  p=line.split("\t")
  if len(p)<12:continue
  try:conf=float(p[10])
  except Exception:continue
  text=p[11].strip()
  if not text or conf<0:continue
  try:key=tuple(int(p[j]) for j in (1,2,3,4))
  except Exception:key=(0,0,0,i)
  rows.append((key,conf,text))
 if not rows:return "",0.0
 grouped={}
 for key,conf,text in rows:
  grouped.setdefault(key,[]).append((conf,text))
 lines=[];confs=[]
 for key in sorted(grouped):
  vals=grouped[key]
  lines.append(" ".join(x[1] for x in vals))
  confs.extend(x[0] for x in vals)
 return "\n".join(lines),sum(confs)/len(confs)

def _ocr_tsv(path:Path,langs:str,psm:int):
 try:
  raw=subprocess.check_output(
   ["tesseract",str(path),"stdout","-l",langs,"--oem","1","--psm",str(psm),
    "-c","preserve_interword_spaces=1","tsv"],
   stderr=subprocess.DEVNULL,text=True,timeout=120
  )
  text,conf=_parse_tsv(raw)
  return {"text":text,"conf":conf,"langs":langs,"psm":psm}
 except Exception:
  return {"text":"","conf":0.0,"langs":langs,"psm":psm}

def _semantic_score(c):
 t=(c.get("text") or "").strip()
 if not t:return -100000.0
 words=[w for w in WORD_RE.findall(t) if len(w)>=2]
 if not words:return -100000.0
 pers=len(PERSIAN_RE.findall(t)); lat=len(LATIN_RE.findall(t))
 total_alpha=max(pers+lat,1)
 pr=pers/total_alpha; lr=lat/total_alpha
 low=t.lower()
 known_fa=sum(1 for w in PERSIAN_COMMON if w in t)
 known_lat=sum(1 for w in LATIN_COMMON if w in low)
 short_noise=sum(1 for w in words if len(w)<=2)
 junk_tokens=sum(1 for w in words if re.search(r"[A-Za-z].*[\u0600-\u06FF]|[\u0600-\u06FF].*[A-Za-z]",w))
 score=c.get("conf",0)*2.2 + min(len(words),120)*0.7 + known_fa*18 + known_lat*12
 if c.get("langs")=="fas":
  score += pr*45 - lr*10
 elif c.get("langs") in ("eng+deu","deu+eng"):
  score += lr*35 - pr*10
 else:
  score += max(pr,lr)*18
 score -= short_noise*0.5 + junk_tokens*8
 if c.get("conf",0)<35:score-=40
 return score

def _ocr_image(src:Path)->str:
 with tempfile.TemporaryDirectory() as td:
  td=Path(td);normal=td/"normal.png";binary=td/"binary.png"
  _prep(src,normal,False);_prep(src,binary,True)
  candidates=[]
  for img in (normal,binary):
   candidates.extend([
    _ocr_tsv(img,"fas",6),_ocr_tsv(img,"fas",11),
    _ocr_tsv(img,"eng+deu",6),_ocr_tsv(img,"eng+deu",11),
    _ocr_tsv(img,"fas+eng+deu",6),_ocr_tsv(img,"fas+eng+deu",11),
   ])
  best=max(candidates,key=_semantic_score,default={"text":"","conf":0})
  # Never propagate OCR garbage into naming/classification.
  if best.get("conf",0)<42 or _semantic_score(best)<55:return ""
  return best.get("text","")

def _native_text_ok(text:str)->bool:
 t=(text or "").strip()
 if len(t)<120:return False
 words=WORD_RE.findall(t)
 if len(words)<18:return False
 weird=sum(1 for w in words if re.search(r"[A-Za-z].*[\u0600-\u06FF]|[\u0600-\u06FF].*[A-Za-z]",w))
 return weird/max(len(words),1)<0.08

def extract_text(path:Path,mime:str|None):
 try:
  if mime=="application/pdf":
   native="\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages[:10])
   if _native_text_ok(native):return native
   with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    subprocess.run(
     ["pdftoppm","-f","1","-l","6","-png","-r","300",str(path),str(td/"page")],
     check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=180
    )
    pages=[]
    for p in sorted(td.glob("page-*.png")):
     txt=_ocr_image(p)
     if txt.strip():pages.append(txt)
    return "\n".join(pages)
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
