import re,unicodedata
from datetime import date
from pathlib import Path

# Deterministic document intelligence. No external AI dependency.
# Weighted phrases are intentionally multilingual because the archive contains
# Persian, German and English documents.
RULES=[
 ("identity","passport",12,["passport","reisepass","گذرنامه","پاسپورت","islamic republic of iran"]),
 ("identity","residence_permit",12,["aufenthaltstitel","niederlassungsbewilligung","residence permit","aufenthaltskarte","rot-weiß-rot","کارت اقامت","اجازه اقامت"]),
 ("identity","id_card",10,["identity card","personalausweis","carta d'identità","کارت ملی","کارت شناسایی","national id"]),
 ("identity","driving_license",10,["driving licence","driving license","führerschein","گواهینامه رانندگی"]),
 ("education","university",8,["university","universität","hochschule","universita","degree","diploma","transcript","enrollment","immatrikulation","دانشگاه","دانشنامه","ریز نمرات","گواهی اشتغال به تحصیل"]),
 ("legal","authority_letter",8,["ma35","magistratsabteilung","magistrat der stadt wien","bescheid","beschwerde","vollmacht","behörde","نامه اداری","وکالتنامه","وکالت نامه"]),
 ("legal","court",8,["gericht","court","urteil","beschluss","دادگاه","رای دادگاه","رأی دادگاه"]),
 ("housing","rental_contract",9,["mietvertrag","hauptmietvertrag","rental agreement","lease agreement","اجاره نامه","اجاره‌نامه","قرارداد اجاره"]),
 ("insurance","health_insurance",9,["ögk","österreichische gesundheitskasse","krankenversicherung","health insurance","بیمه درمان","بیمه سلامت"]),
 ("insurance","legal_insurance",9,["arag","rechtsschutz","legal insurance","بیمه حقوقی"]),
 ("insurance","life_insurance",9,["lebensversicherung","life insurance","بیمه عمر"]),
 ("finance","bank_statement",8,["kontoauszug","bank statement","account statement","iban","bic","صورت حساب بانکی","صورتحساب بانکی","گردش حساب"]),
 ("finance","bank_letter",8,["mittelherkunft","bank confirmation","bankbestätigung","bank letter","گواهی بانکی","نامه بانک"]),
 ("employment","employment_contract",8,["arbeitsvertrag","dienstvertrag","employment contract","قرارداد کار","قرارداد استخدام"]),
 ("employment","salary",8,["gehaltsabrechnung","lohnabrechnung","salary slip","payslip","فیش حقوق","فیش حقوقی"]),
 ("tax","tax",8,["finanzamt","steuerbescheid","tax office","tax return","مالیات","اداره مالیات"]),
 ("invoice","invoice",7,["invoice","rechnung","faktura","فاکتور","صورتحساب"]),
 ("contract","contract",6,["vertrag","agreement","contract","قرارداد"]),
 ("letter","letter",5,["betreff","subject:","موضوع:","موضوع ","dear sir","sehr geehrte","با سلام"]),
]

COUNTRIES={
 "austria":["austria","österreich","اتریش"],
 "italy":["italy","italia","ایتالیا"],
 "iran":["iran","iranian","islamic republic of iran","ایران"],
 "germany":["germany","deutschland","آلمان"],
 "turkey":["turkey","türkiye","ترکیه"],
}

ISSUERS=[
 ("MA35",["ma35","magistratsabteilung 35"]),
 ("ÖGK",["ögk","österreichische gesundheitskasse"]),
 ("ARAG",["arag"]),
 ("Erste Bank",["erste bank","erste österreichische","sparkasse"]),
 ("Finanzamt Österreich",["finanzamt österreich"]),
 ("Magistrat Wien",["magistrat der stadt wien","stadt wien"]),
]

LABELS={
 "passport":"گذرنامه",
 "residence_permit":"کارت اقامت",
 "id_card":"کارت شناسایی",
 "driving_license":"گواهینامه رانندگی",
 "university":"مدرک دانشگاهی",
 "authority_letter":"نامه اداری",
 "court":"سند دادگاه",
 "rental_contract":"قرارداد اجاره",
 "health_insurance":"بیمه درمان",
 "legal_insurance":"بیمه حقوقی",
 "life_insurance":"بیمه عمر",
 "bank_statement":"صورتحساب بانکی",
 "bank_letter":"نامه بانکی",
 "employment_contract":"قرارداد کاری",
 "salary":"فیش حقوقی",
 "tax":"سند مالیاتی",
 "invoice":"فاکتور",
 "contract":"قرارداد",
 "letter":"نامه",
 "other":"سند",
}

GENERIC_FILE_RE=re.compile(r"^(scan|img|image|document|doc|photo|screenshot)[ _-]*[0-9_-]*$",re.I)
BAD_HEADING_WORDS={
 "page","seite","scan","document","image","signature","unterschrift","www","http",
 "telefon","phone","fax","email","e-mail"
}

def norm(s):
 s=unicodedata.normalize("NFKC",s or "").lower()
 s=s.replace("\u200c"," ")
 return re.sub(r"\s+"," ",s).strip()

def _original_filename(filename):
 s=Path(filename or "").name
 if s.startswith("gdrive__") and s.count("__")>=2:
  s=s.split("__",2)[2]
 return s

def _letters_ratio(s):
 if not s:return 0
 useful=sum(ch.isalpha() for ch in s)
 return useful/max(len(s),1)

def _clean_line(s):
 s=re.sub(r"\s+"," ",s or "").strip(" \t\r\n|:;,_-")
 return s[:140]

def meaningful_heading(text):
 lines=[_clean_line(x) for x in (text or "").splitlines()]
 candidates=[]
 for i,line in enumerate(lines[:60]):
  if len(line)<5 or len(line)>140:continue
  n=norm(line)
  if _letters_ratio(line)<0.45:continue
  if any(w in n for w in BAD_HEADING_WORDS):continue
  if re.fullmatch(r"[\d\W_]+",line):continue
  score=0
  if i<12:score+=4
  if 8<=len(line)<=80:score+=3
  if line.upper()==line and sum(c.isalpha() for c in line)>=5:score+=2
  if any(k in n for k in ["bescheid","bestätigung","vertrag","rechnung","statement","certificate","گواهی","قرارداد","نامه","فاکتور","صورتحساب"]):score+=5
  score+=min(sum(c.isalpha() for c in line)//8,4)
  candidates.append((score,-i,line))
 return max(candidates,default=(0,0,None))[2]

def subject(text):
 pats=[
  r"(?im)^\s*(?:betreff|subject|موضوع)\s*[:\-]?\s*(.{4,120})$",
  r"(?im)^\s*(?:re)\s*[:\-]\s*(.{4,120})$",
 ]
 for p in pats:
  m=re.search(p,text or "")
  if m:
   s=_clean_line(m.group(1))
   if _letters_ratio(s)>=0.35:return s
 return None

def dates(text):
 out=[]
 patterns=[
  r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.]([0-2]?\d|3[01])\b",
  r"\b([0-2]?\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](20\d{2})\b",
 ]
 for p in patterns:
  for m in re.finditer(p,text or ""):
   g=m.groups()
   try:
    if len(g[0])==4:y,mo,d=map(int,g)
    else:d,mo,y=map(int,g)
    x=date(y,mo,d)
    if date(1990,1,1)<=x<=date(2100,12,31):out.append(x)
   except Exception:pass
 return sorted(set(out))

def document_number(text,subtype):
 patterns={
  "passport":[r"(?:passport\s*(?:no|number|nr)?\.?\s*[:#-]?\s*)([a-z0-9]{6,12})",r"\b([a-z][0-9]{7,9})\b"],
  "residence_permit":[r"(?:card|permit|document)\s*(?:no|number|nr)?\.?\s*[:#-]?\s*([a-z0-9-]{6,20})"],
  "id_card":[r"(?:id|identity|national)\s*(?:no|number)?\.?\s*[:#-]?\s*([a-z0-9-]{6,20})"],
  "driving_license":[r"(?:licen[cs]e|führerschein)\s*(?:no|number|nr)?\.?\s*[:#-]?\s*([a-z0-9-]{5,20})"],
  "invoice":[r"(?:invoice|rechnung|فاکتور)\s*(?:no|number|nr|شماره)?\.?\s*[:#-]?\s*([a-z0-9\-/]{3,24})"],
 }
 for p in patterns.get(subtype,[]):
  m=re.search(p,text or "",re.I)
  if m:return m.group(1).upper()
 return None

def person_name(text):
 raw=text or ""
 patterns=[
  r"(?im)^\s*(?:surname|family name|last name|نام خانوادگی)\s*[:\-]?\s*([A-Za-zآ-ی][A-Za-zآ-ی .\-]{2,45})$",
  r"(?im)^\s*(?:given names?|first name|نام)\s*[:\-]?\s*([A-Za-zآ-ی][A-Za-zآ-ی .\-]{2,45})$",
  r"(?im)^\s*(?:name|نام و نام خانوادگی)\s*[:\-]?\s*([A-Za-zآ-ی][A-Za-zآ-ی .\-]{3,60})$",
 ]
 vals=[]
 for p in patterns:
  m=re.search(p,raw)
  if m:
   v=_clean_line(m.group(1))
   if v and v not in vals:vals.append(v)
 return " ".join(vals[:2]) or None

def useful_source_title(filename):
 stem=Path(_original_filename(filename)).stem
 stem=re.sub(r"[_]+"," ",stem).strip(" .-_")
 if not stem or GENERIC_FILE_RE.match(stem):return None
 if re.match(r"^(scan|img|image|document|doc)[ _-]*\d",stem,re.I):return None
 return stem[:100] if len(stem)>=3 else None

def _rule_score(t,fname,keys,base):
 hits=0
 for k in keys:
  nk=norm(k)
  if nk in t:hits+=2
  if nk in fname:hits+=1
 return base+hits*2 if hits else 0

def classify(text,filename=""):
 original=_original_filename(filename)
 t=norm(text)
 fname=norm(Path(original).stem.replace("_"," ").replace("-"," "))
 best=("other","other",0,[])
 for cat,sub,base,keys in RULES:
  score=_rule_score(t,fname,keys,base)
  matched=[k for k in keys if norm(k) in t or norm(k) in fname]
  if score>best[2]:best=(cat,sub,score,matched)

 cat,sub,score,matched=best
 if score==0:
  cat=sub="other"

 country=None
 for c,keys in COUNTRIES.items():
  if any(norm(k) in t for k in keys):country=c;break

 issuer=None
 for name,keys in ISSUERS:
  if any(norm(k) in t for k in keys):issuer=name;break

 ds=dates(t)
 number=document_number(text or "",sub)
 person=person_name(text or "")
 subj=subject(text or "")
 heading=meaningful_heading(text or "")
 issue=ds[0] if ds else None
 expiry=ds[-1] if len(ds)>1 else None

 label=LABELS.get(sub,"سند")
 parts=[label]
 if subj and norm(subj) not in norm(label):parts.append(subj)
 elif issuer:parts.append(issuer)
 elif heading and norm(heading) not in norm(label):parts.append(heading)
 if person and person.lower() not in " ".join(parts).lower():parts.append(person.title())
 if number:parts.append(number)

 # Fallback must still be content-derived when OCR found usable text.
 if sub=="other":
  if subj:title=subj
  elif heading:title=heading
  else:title=useful_source_title(original) or "سند اسکن‌شده"
 else:
  title=" - ".join(x for x in parts if x)

 # Keep titles usable in UI and filenames.
 title=re.sub(r"\s+"," ",title).strip(" .-_")[:180]
 if not title:title="سند"

 if score>=14:confidence="high"
 elif score>=8:confidence="medium"
 elif heading or subj:confidence="medium"
 else:confidence="low"

 return {
  "title":title,
  "category":cat,
  "subtype":sub,
  "country":country,
  "issuer":issuer,
  "document_number":number,
  "issue_date":issue,
  "expiry_date":expiry,
  "person_name":person,
  "subject":subj,
  "heading":heading,
  "confidence":confidence,
  "score":score,
  "matched":matched[:8],
 }

def canonical_filename(meta,ext):
 safe=re.sub(r"[^\w\-. ()\u0600-\u06ff]+","_",meta.get("title") or "Document",flags=re.UNICODE).strip(" ._")
 ext=(ext or "").lower()
 return (safe[:180] or "Document")+ext
