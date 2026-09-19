import re,json,unicodedata
from datetime import datetime,date
from pathlib import Path

RULES=[
 ("identity","passport",["passport","reisepass","passeport","islamic republic of iran","گذرنامه","پاسپورت"]),
 ("identity","residence_permit",["aufenthaltstitel","residence permit","niederlassungsbewilligung","aufenthaltskarte","rot-weiß-rot","اقامت"]),
 ("identity","id_card",["identity card","personalausweis","carta d'identità","codice fiscale","کارت ملی","national id"]),
 ("identity","driving_license",["driving licence","driving license","driver license","führerschein","گواهینامه"]),
 ("education","university",["university","universität","hochschule","universita","laurea","degree","diploma","transcript","دانشگاه","دانشنامه","ریز نمرات","enrollment","immatrikulation"]),
 ("legal","authority_letter",["ma35","magistratsabteilung","magistrat der stadt wien","behörde","bescheid","beschwerde","vollmacht","authority","amt","اداره"]),
 ("housing","rental_contract",["mietvertrag","rental agreement","lease agreement","hauptmietvertrag","اجاره نامه","قرارداد اجاره"]),
 ("insurance","health_insurance",["ögk","österreichische gesundheitskasse","krankenversicherung","health insurance","بیمه درمان"]),
 ("insurance","legal_insurance",["arag","rechtsschutz","legal insurance","بیمه حقوقی"]),
 ("insurance","life_insurance",["lebensversicherung","life insurance","بیمه عمر"]),
 ("finance","bank_statement",["kontoauszug","bank statement","account statement","iban","bic","صورت حساب بانکی"]),
 ("finance","bank_letter",["mittelherkunft","bank confirmation","bank letter","bankbestätigung"]),
 ("employment","employment_contract",["arbeitsvertrag","dienstvertrag","employment contract","قرارداد کار"]),
 ("employment","salary",["gehaltsabrechnung","lohnabrechnung","salary slip","payslip","فیش حقوق"]),
 ("tax","tax",["finanzamt","steuer","tax office","مالیات"]),
 ("invoice","invoice",["invoice","rechnung","faktura","فاکتور"]),
 ("contract","contract",["vertrag","agreement","contract","قرارداد"]),
 ("legal","court",["gericht","court","دادگاه","beschluss","urteil"]),
]

COUNTRIES={
 "austria":["austria","österreich","اتریش"],
 "italy":["italy","italia","ایتالیا"],
 "iran":["iran","iranian","ایران"],
 "germany":["germany","deutschland","آلمان"],
 "turkey":["turkey","türkiye","ترکیه"],
}

ISSUERS=[
 ("MA35",["ma35","magistratsabteilung 35"]),
 ("ÖGK",["ögk","österreichische gesundheitskasse"]),
 ("ARAG",["arag"]),
 ("Erste Bank",["erste bank","sparkasse"]),
 ("Finanzamt Österreich",["finanzamt österreich"]),
]

DATE_PATTERNS=[
 r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.]([0-2]?\d|3[01])\b",
 r"\b([0-2]?\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](20\d{2})\b",
]

def norm(s):
 s=unicodedata.normalize("NFKC",s or "").lower()
 return re.sub(r"\s+"," ",s)

def dates(text):
 out=[]
 for p in DATE_PATTERNS:
  for m in re.finditer(p,text):
   g=m.groups()
   try:
    if len(g[0])==4:y,mo,d=map(int,g)
    else:d,mo,y=map(int,g)
    x=date(y,mo,d)
    if date(1990,1,1)<=x<=date(2100,12,31):out.append(x)
   except:pass
 return sorted(set(out))

def document_number(text,subtype):
 patterns={
  "passport":[r"(?:passport\s*(?:no|number|nr)?\.?\s*[:#-]?\s*)([a-z0-9]{6,12})",r"\b([a-z][0-9]{7,9})\b"],
  "residence_permit":[r"(?:card|permit|document)\s*(?:no|number|nr)?\.?\s*[:#-]?\s*([a-z0-9-]{6,20})"],
  "id_card":[r"(?:id|identity|national)\s*(?:no|number)?\.?\s*[:#-]?\s*([a-z0-9-]{6,20})"],
  "driving_license":[r"(?:licen[cs]e|führerschein)\s*(?:no|number|nr)?\.?\s*[:#-]?\s*([a-z0-9-]{5,20})"],
 }
 for p in patterns.get(subtype,[]):
  m=re.search(p,text,re.I)
  if m:return m.group(1).upper()
 return None

def person_name(text):
 t=norm(text)
 patterns=[
  r"(?:surname|last name|نام خانوادگی)[:\\s]+([a-zآ-ی][a-zآ-ی \\-]{2,40})",
  r"(?:given names?|first name|نام)[:\\s]+([a-zآ-ی][a-zآ-ی \\-]{2,40})",
 ]
 vals=[]
 for p in patterns:
  m=re.search(p,t,re.I)
  if m:
   v=" ".join(m.group(1).split())[:60]
   if v and v not in vals: vals.append(v)
 return " ".join(vals[:2]) or None

def useful_source_title(filename):
 s=_original_filename(filename)
 stem=Path(s).stem
 stem=re.sub(r"^(scan|img|image|document)[ _-]*\d.*$","",stem,flags=re.I)
 stem=re.sub(r"[_]+"," ",stem).strip(" .-_")
 return stem[:100] if len(stem)>=3 else None

def _original_filename(filename):
 s=filename or ""
 if s.startswith("gdrive__") and s.count("__")>=2:s=s.split("__",2)[2]
 return s

def classify(text,filename=""):
 original=_original_filename(filename)
 t=norm((text or "")+" "+original)
 fname=norm(Path(original).stem.replace("_"," ").replace("-"," "))
 filename_hints=[
  ("identity","passport",["passport","پاسپورت","گذرنامه"]),
  ("identity","driving_license",["driving","license","licence","گواهینامه"]),
  ("education","university",["لیسانس","دانشگاه","degree","diploma","university","certificate","گواهینامه tuf"]),
  ("legal","authority_letter",["ma35","beschwerde","vollmacht","وکالت"]),
  ("housing","rental_contract",["mietvertrag","اجاره"]),
  ("insurance","legal_insurance",["arag"]),
  ("finance","bank_statement",["bank","konto","erste"]),
 ]

 best=("other","other",0)
 for cat,sub,keys in RULES:
  score=sum(2 for k in keys if k in t) + (2 if sum(1 for k in keys if k in t)>=2 else 0)
  if score>best[2]:best=(cat,sub,score)
 for cat0,sub0,keys in filename_hints:
  score=sum(2 if k in fname else 0 for k in keys)
  if score>best[2]:best=(cat0,sub0,score)
 cat,sub,_=best
 country=None
 for c,keys in COUNTRIES.items():
  if any(k in t for k in keys):country=c;break
 issuer=None
 for name,keys in ISSUERS:
  if any(k in t for k in keys):issuer=name;break
 ds=dates(t)
 number=document_number(t,sub)
 person=person_name(t)
 issue=ds[0] if ds else None
 expiry=ds[-1] if len(ds)>1 else None
 label={
  "passport":"Passport","residence_permit":"Residence Permit","id_card":"ID Card","driving_license":"Driving License",
  "health_insurance":"Health Insurance","legal_insurance":"Legal Insurance","life_insurance":"Life Insurance",
  "rental_contract":"Rental Contract","bank_statement":"Bank Statement","bank_letter":"Bank Letter",
  "employment_contract":"Employment Contract","salary":"Salary Slip","university":"University Document",
  "court":"Court Document","authority_letter":"Authority Letter","tax":"Tax Document","invoice":"Invoice","contract":"Contract",
 }.get(sub,"Document")
 if sub=="other":
  hint=useful_source_title(original)
  if hint: label=hint
 parts=[label]
 if person:parts.append(person.title())
 if issuer:parts.append(issuer)
 if number:parts.append(number)
 if expiry:parts.append("exp-"+expiry.isoformat())
 title=" - ".join(parts)
 return {
  "title":title,"category":cat,"subtype":sub,"country":country,"issuer":issuer,
  "document_number":number,"issue_date":issue,"expiry_date":expiry,"person_name":person,
  "confidence":"high" if best[2]>=6 else ("medium" if best[2]>=2 else "low")
 }

def canonical_filename(meta,ext):
 safe=re.sub(r"[^\w\-. ()]+","_",meta.get("title") or "Document",flags=re.UNICODE).strip(" ._")
 return (safe[:180] or "Document")+(ext.lower() if ext else "")
