import json
import re
from datetime import datetime
from pathlib import Path

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
CHARMAP = str.maketrans({"ي":"ی","ى":"ی","ئ":"ی","ك":"ک","ۀ":"ه","ة":"ه","ؤ":"و","ـ":" "})

# Ordered from specific to generic. A specific rule wins when it has an anchor.
RULES = [
 ("کارت ملی","identity",["کارت ملی","کارت شناسایی ملی","national identity card","national id","شماره ملی"]),
 ("شناسنامه","identity",["شناسنامه","سازمان ثبت احوال کشور","ثبت احوال"]),
 ("گذرنامه","identity",["passport","reisepass","گذرنامه","پاسپورت"]),
 ("کارت اقامت","identity",["aufenthaltstitel","niederlassungsbewilligung","residence permit","کارت اقامت"]),
 ("گواهینامه","identity",["führerschein","driving licence","driving license","گواهینامه"]),
 ("نامه MA35","legal",["ma35","magistratsabteilung 35"]),
 ("قرارداد اجاره","housing",["mietvertrag","rental agreement","lease agreement","قرارداد اجاره","اجاره نامه"]),
 ("صورتحساب بانکی","finance",["kontoauszug","bank statement","account statement","گردش حساب","صورتحساب بانکی"]),
 ("نامه بانکی","finance",["mittelherkunft","bankbestätigung","bank confirmation","گواهی بانکی","نامه بانک"]),
 ("بیمه","insurance",["versicherung","insurance","rechtsschutz","بیمه"]),
 ("مدرک تحصیلی","education",["university","universität","hochschule","diploma","transcript","دانشگاه","دانشنامه","ریز نمرات"]),
 ("قرارداد کاری","employment",["arbeitsvertrag","dienstvertrag","employment contract","قرارداد کار","قرارداد استخدام"]),
 ("فیش حقوقی","employment",["gehaltsabrechnung","lohnabrechnung","payslip","salary slip","فیش حقوق"]),
 ("سند مالیاتی","tax",["finanzamt","steuerbescheid","tax office","مالیات"]),
 ("فاکتور","invoice",["rechnung","invoice","faktura","فاکتور","صورتحساب"]),
 ("رأی یا نامه حقوقی","legal",["bescheid","gericht","beschwerde","court","دادگاه","وکالتنامه","وکالت نامه"]),
 ("قرارداد","contract",["vertrag","agreement","contract","قرارداد"]),
]

ISSUERS = [
 ("MA35",["ma35","magistratsabteilung 35"]),("ARAG",["arag"]),
 ("ÖGK",["ögk","österreichische gesundheitskasse"]),("Erste Bank",["erste bank","sparkasse"]),
 ("Finanzamt Österreich",["finanzamt österreich","finanzamt"]),
]
COUNTRIES = [
 ("IR",["islamic republic of iran","جمهوری اسلامی ایران","iranian","ایران"]),
 ("AT",["republik österreich","österreich","austria","اتریش"]),
 ("DE",["bundesrepublik deutschland","deutschland","germany","آلمان"]),
 ("IT",["repubblica italiana","italia","italy","ایتالیا"]),
 ("TR",["türkiye cumhuriyeti","türkiye","turkey","ترکیه"]),
 ("AE",["united arab emirates","الإمارات العربية المتحدة","امارات"]),
 ("FR",["république française","france","فرانسه"]),
 ("CH",["swiss confederation","schweizerische eidgenossenschaft","switzerland","سوئیس"]),
]

def clean(text):
    text = (text or "").translate(DIGITS).translate(CHARMAP).replace("\u200c"," ").replace("\ufeff"," ")
    text = re.sub(r"[\u064b-\u065f]", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()

def normalize_name(text):
    text = clean(text)
    text = re.sub(r"[^\w\u0600-\u06ff\s-]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()

def safe_part(value):
    value = re.sub(r"\s+", "_", str(value or "").strip())
    value = re.sub(r"[^\w\u0600-\u06ffäöüÄÖÜß.-]+", "_", value, flags=re.UNICODE)
    return re.sub(r"_+", "_", value).strip(" ._-")

def extract_date(text):
    normalized=(text or "").translate(DIGITS)
    for pattern,order in [
      (r"\b(20\d{2}|1[34]\d{2})[./-](0?[1-9]|1[0-2])[./-]([0-2]?\d|3[01])\b","ymd"),
      (r"\b([0-2]?\d|3[01])[./-](0?[1-9]|1[0-2])[./-](20\d{2}|1[34]\d{2})\b","dmy")]:
        m=re.search(pattern,normalized)
        if m:
            a,b,c=map(int,m.groups()); year,month,day=(a,b,c) if order=="ymd" else (c,b,a)
            if 1<=month<=12 and 1<=day<=31:return f"{year:04d}-{month:02d}-{day:02d}",True
    return datetime.now().strftime("%Y-%m-%d"),False

def extract_reference(text):
    normalized=(text or "").translate(DIGITS)
    patterns=[
      r"(?:aktenzeichen|geschäftszahl|reference|ref\.?|شماره پرونده|شماره سند)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/.]{3,28})",
      r"(?:invoice|rechnung|فاکتور)\s*(?:no|number|nr|شماره)?\.?\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/.]{2,20})",
      r"(?:passport|reisepass|گذرنامه)\s*(?:no|number|nr|شماره)?\.?\s*[:#-]?\s*([A-Z0-9-]{5,16})"]
    for p in patterns:
        m=re.search(p,normalized,re.I)
        if m:return m.group(1).upper().strip(".-/")
    return ""

def _person_part(value,script="any"):
    value=str(value or "").replace("<"," ")
    value=re.split(r"\s{2,}|\b(?:date|datum|birth|nationality|sex|gender|geburtsdatum|نام پدر|تاریخ تولد|شماره ملی)\b",value,maxsplit=1,flags=re.I)[0]
    if script=="fa":value=re.sub(r"[^\u0600-\u06ff\s‌-]"," ",value)
    elif script=="latin":value=re.sub(r"[^A-Za-zÀ-ž\s'-]"," ",value)
    value=re.sub(r"\s+"," ",value).strip(" -_'‌")
    return " ".join([w for w in value.split() if len(w)>=2][:5])

def labeled_value(text,labels,script="any"):
    # OCR often puts a label in the middle of a line, so don't require line start.
    m=re.search(r"(?:^|[\n\r|])?\s*(?:"+"|".join(labels)+r")\s*[:：\-]?\s*([^\n\r|]{2,80})",text or "",re.I|re.M)
    return _person_part(m.group(1),script) if m else ""

def extract_person_name(text):
    raw=(text or "").translate(DIGITS).translate(CHARMAP)
    full=labeled_value(raw,[r"نام\s*و\s*نام\s*خانوادگی",r"نام\s*کامل",r"نام\s*دارنده"],"fa")
    if full:return full
    family=labeled_value(raw,[r"نام\s*خانوادگی",r"نام\s*فامیل"],"fa")
    given=labeled_value(raw,[r"نام(?!\s*(?:خانوادگی|پدر|مادر))"],"fa")
    if given and family:return f"{given} {family}"
    if given:return given
    surname=labeled_value(raw,[r"surname",r"family\s*name",r"last\s*name",r"nachname",r"familienname"],"latin")
    given=labeled_value(raw,[r"given\s*names?",r"first\s*name",r"forename",r"vorname"],"latin")
    if given and surname:return f"{given} {surname}".title()
    if given:return given.title()
    mrz=re.search(r"P<[A-Z]{3}([A-Z]+(?:<[A-Z]+)*)<<([A-Z]+(?:<[A-Z]+)*)",(raw or "").upper())
    if mrz:return " ".join(filter(None,[_person_part(mrz.group(2),"latin"),_person_part(mrz.group(1),"latin")])).title()
    return ""

def identity_number(text):
    t=(text or "").translate(DIGITS)
    for p in [r"\b\d{10}\b",r"\b[A-Z]{1,2}\d{6,9}\b"]:
        m=re.search(p,t,re.I)
        if m:return m.group(0)
    return ""

def detect_country(text):
    t=clean(text)
    for code,keys in COUNTRIES:
        if any(k.casefold() in t for k in keys):return code
    return ""

def analyze_document(text,original_name=""):
    normalized=clean(text)
    candidates=[]
    for idx,(label,category,keys) in enumerate(RULES):
        found=[k for k in keys if clean(k) in normalized]
        if found:
            # Specific rules are preferred; generic contract/invoice needs more evidence.
            score=sum(1.0 if len(k)>6 else .75 for k in found)+(0.08*(len(RULES)-idx))
            candidates.append((score,label,category,found))
    if candidates:
        _,doc_type,category,found=max(candidates,key=lambda x:x[0])
    else:doc_type,category,found="سند","other",[]
    issuer=next((name for name,keys in ISSUERS if any(clean(k) in normalized for k in keys)),"")
    date,date_found=extract_date(text); reference=extract_reference(text); person=extract_person_name(text)
    country=detect_country(text); id_number=identity_number(text)
    person_conf=0.0
    if person:person_conf=0.55+(0.2 if re.search(r"(نام\s*(?:و\s*)?نام\s*خانوادگی|surname|given|name of holder)",text or "",re.I) else 0.0)+(0.15 if id_number else 0.0)
    type_conf=min(0.98,0.42+0.16*len(found)+(0.10 if issuer else 0.0)+(0.08 if category!="other" else 0.0))
    reasons=[]
    if found:reasons.append("کلیدواژه‌های تشخیص: "+", ".join(found[:5]))
    if issuer:reasons.append("صادرکننده/مرجع شناسایی شد")
    if person:reasons.append("نام از فیلد نام‌دار OCR استخراج شد")
    if id_number:reasons.append("شناسهٔ هویتی/مرجع پیدا شد")
    if not found:reasons.append("کلیدواژهٔ کافی برای نوع سند پیدا نشد")
    if person and person_conf<0.85:reasons.append("نام صاحب سند نیازمند تأیید دستی است")
    ext=Path(original_name or "").suffix.lower()
    if ext not in {".pdf",".jpg",".jpeg",".png",".webp",".tif",".tiff"}:ext=".pdf"
    parts=[date,doc_type,person,country,issuer,reference]
    smart_filename="_".join(filter(None,(safe_part(x) for x in parts)))[:220]+ext
    title_parts=[doc_type]+([person] if person else [])+([issuer] if issuer and issuer.casefold() not in doc_type.casefold() else [])+([reference] if reference else [])
    suggested_title=" - ".join(title_parts)
    confidence=min(0.97,0.32+min(0.32,len(found)*0.10)+(0.10 if issuer else 0)+(0.08 if date_found else 0)+(0.08 if reference else 0)+(0.08 if person else 0)+(0.04 if len(normalized)>=120 else 0))
    entities={"issuer":issuer,"date":date if date_found else "","reference":reference,"person_name":person,"person_confidence":round(person_conf,3),"identity_number":id_number,"country":country,"keywords":found,"confidence_reasons":reasons,"document_type_confidence":round(type_conf,3),"source_filename":original_name}
    return {
      "smart_filename":smart_filename,"suggested_title":suggested_title,"document_type":doc_type,"category":category,"country":country,
      "description_fa":f"نوع پیشنهادی: {doc_type}؛ صاحب احتمالی: {person or 'نامشخص'}؛ صادرکننده احتمالی: {issuer or 'نامشخص'}؛ نیازمند تأیید: {'بله' if type_conf<0.78 or (person and person_conf<0.85) else 'خیر'}.",
      "description_de":f"Dokumenttyp: {doc_type}; möglicher Name: {person or 'unbekannt'}; bitte prüfen.",
      "ai_confidence":confidence,"extracted_entities":json.dumps(entities,ensure_ascii=False)
    }
