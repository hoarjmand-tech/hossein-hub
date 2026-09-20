import json
import re
from datetime import datetime
from pathlib import Path


RULES = [
    ("شناسنامه", "identity", ["شناسنامه", "سازمان ثبت احوال کشور", "ثبت احوال"]),
    ("کارت ملی", "identity", ["کارت ملی", "کارت شناسایی ملی", "national identity card", "شماره ملی"]),
    ("گذرنامه", "identity", ["passport", "reisepass", "گذرنامه", "پاسپورت"]),
    ("کارت اقامت", "identity", ["aufenthaltstitel", "niederlassungsbewilligung", "residence permit", "کارت اقامت"]),
    ("گواهینامه", "identity", ["führerschein", "driving licence", "driving license", "گواهینامه"]),
    ("نامه MA35", "legal", ["ma35", "magistratsabteilung 35"]),
    ("رأی یا نامه حقوقی", "legal", ["bescheid", "gericht", "beschwerde", "court", "دادگاه", "وکالتنامه", "وکالت نامه"]),
    ("قرارداد اجاره", "housing", ["mietvertrag", "rental agreement", "lease agreement", "قرارداد اجاره", "اجاره نامه"]),
    ("بیمه", "insurance", ["versicherung", "insurance", "rechtsschutz", "بیمه"]),
    ("صورتحساب بانکی", "finance", ["kontoauszug", "bank statement", "account statement", "گردش حساب", "صورتحساب بانکی"]),
    ("نامه بانکی", "finance", ["mittelherkunft", "bankbestätigung", "bank confirmation", "گواهی بانکی", "نامه بانک"]),
    ("مدرک تحصیلی", "education", ["university", "universität", "hochschule", "diploma", "transcript", "دانشگاه", "دانشنامه", "ریز نمرات"]),
    ("قرارداد کاری", "employment", ["arbeitsvertrag", "dienstvertrag", "employment contract", "قرارداد کار", "قرارداد استخدام"]),
    ("فیش حقوقی", "employment", ["gehaltsabrechnung", "lohnabrechnung", "payslip", "salary slip", "فیش حقوق"]),
    ("سند مالیاتی", "tax", ["finanzamt", "steuerbescheid", "tax office", "مالیات"]),
    ("فاکتور", "invoice", ["rechnung", "invoice", "faktura", "فاکتور", "صورتحساب"]),
    ("قرارداد", "contract", ["vertrag", "agreement", "contract", "قرارداد"]),
]

ISSUERS = [
    ("MA35", ["ma35", "magistratsabteilung 35"]),
    ("ARAG", ["arag"]),
    ("ÖGK", ["ögk", "österreichische gesundheitskasse"]),
    ("Erste Bank", ["erste bank", "sparkasse"]),
    ("Finanzamt Österreich", ["finanzamt österreich", "finanzamt"]),
]

COUNTRIES = [
    ("IR", ["islamic republic of iran", "جمهوری اسلامی ایران", "iranian", "ایران"]),
    ("AT", ["republik österreich", "österreich", "austria", "اتریش"]),
    ("DE", ["bundesrepublik deutschland", "deutschland", "germany", "آلمان"]),
    ("IT", ["repubblica italiana", "italia", "italy", "ایتالیا"]),
    ("TR", ["türkiye cumhuriyeti", "türkiye", "turkey", "ترکیه"]),
    ("AE", ["united arab emirates", "الإمارات العربية المتحدة", "امارات"]),
    ("FR", ["république française", "france", "فرانسه"]),
    ("CH", ["swiss confederation", "schweizerische eidgenossenschaft", "switzerland", "سوئیس"]),
]

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def clean(text):
    return re.sub(r"\s+", " ", (text or "").translate(DIGITS)).strip().lower()


def safe_part(value):
    value = re.sub(r"\s+", "_", str(value or "").strip())
    value = re.sub(r"[^\w\u0600-\u06ffäöüÄÖÜß.-]+", "_", value, flags=re.UNICODE)
    return re.sub(r"_+", "_", value).strip(" ._-")


def extract_date(text):
    normalized = (text or "").translate(DIGITS)
    patterns = [
        (r"\b(20\d{2}|1[34]\d{2})[./-](0?[1-9]|1[0-2])[./-]([0-2]?\d|3[01])\b", "ymd"),
        (r"\b([0-2]?\d|3[01])[./-](0?[1-9]|1[0-2])[./-](20\d{2}|1[34]\d{2})\b", "dmy"),
    ]
    for pattern, order in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        a, b, c = [int(x) for x in match.groups()]
        year, month, day = (a, b, c) if order == "ymd" else (c, b, a)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}", True
    return datetime.now().strftime("%Y-%m-%d"), False


def extract_reference(text):
    normalized = (text or "").translate(DIGITS)
    patterns = [
        r"(?:aktenzeichen|geschäftszahl|reference|ref\.?|شماره پرونده|شماره سند)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/.]{3,28})",
        r"(?:invoice|rechnung|فاکتور)\s*(?:no|number|nr|شماره)?\.?\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/.]{2,20})",
        r"(?:passport|reisepass|گذرنامه)\s*(?:no|number|nr|شماره)?\.?\s*[:#-]?\s*([A-Z0-9-]{5,16})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            return match.group(1).upper().strip(".-/")
    return ""


def clean_person_part(value, script="any"):
    value = str(value or "").replace("<", " ")
    value = re.split(
        r"\s{2,}|\b(?:date|datum|birth|nationality|sex|gender|geburtsdatum|نام پدر|تاریخ تولد|شماره ملی)\b",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    if script == "fa":
        value = re.sub(r"[^\u0600-\u06ff\s‌-]", " ", value)
    elif script == "latin":
        value = re.sub(r"[^A-Za-zÀ-ž\s'-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_'‌")
    words = [word for word in value.split() if len(word) >= 2][:4]
    return " ".join(words)


def labeled_value(text, labels, script="any"):
    joined = "|".join(labels)
    match = re.search(
        rf"(?:^|[\n\r|])\s*(?:{joined})\s*[:：\-]?\s*([^\n\r|]{{2,70}})",
        text or "",
        re.I | re.M,
    )
    return clean_person_part(match.group(1), script) if match else ""


def extract_person_name(text):
    raw = (text or "").translate(DIGITS)

    full_fa = labeled_value(
        raw,
        [r"نام\s*و\s*نام\s*خانوادگی", r"نام\s*کامل", r"نام\s*دارنده"],
        "fa",
    )
    if full_fa:
        return full_fa

    family_fa = labeled_value(raw, [r"نام\s*خانوادگی", r"نام\s*فامیل"], "fa")
    given_fa = labeled_value(raw, [r"نام(?!\s*(?:خانوادگی|پدر|مادر))"], "fa")
    if given_fa and family_fa:
        return f"{given_fa} {family_fa}"
    if given_fa:
        return given_fa

    surname = labeled_value(
        raw,
        [r"surname", r"family\s*name", r"last\s*name", r"nachname", r"familienname"],
        "latin",
    )
    given = labeled_value(
        raw,
        [r"given\s*names?", r"first\s*name", r"forename", r"vorname"],
        "latin",
    )
    if given and surname:
        return f"{given} {surname}".title()
    if given:
        return given.title()

    mrz = re.search(
        r"P<[A-Z]{3}([A-Z]+(?:<[A-Z]+)*)<<([A-Z]+(?:<[A-Z]+)*)",
        raw.upper(),
    )
    if mrz:
        family = clean_person_part(mrz.group(1), "latin")
        given = clean_person_part(mrz.group(2), "latin")
        if given or family:
            return " ".join(filter(None, [given, family])).title()
    return ""


def detect_country(text):
    normalized=clean(text)
    for code,keywords in COUNTRIES:
        if any(keyword.lower() in normalized for keyword in keywords):
            return code
    return ""


def analyze_document(text, original_name=""):
    normalized = clean(text)
    best = None
    for label, category, keywords in RULES:
        hits = [key for key in keywords if key.lower() in normalized]
        if hits and (best is None or len(hits) > len(best[2])):
            best = (label, category, hits)

    if best:
        doc_type, category, found = best
    else:
        doc_type, category, found = "سند", "other", []

    issuer = ""
    for issuer_name, keywords in ISSUERS:
        if any(key.lower() in normalized for key in keywords):
            issuer = issuer_name
            break

    date, date_found = extract_date(text)
    reference = extract_reference(text)
    person_name = extract_person_name(text)
    country = detect_country(text)
    extension = Path(original_name or "").suffix.lower()
    if extension not in {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
        extension = ".pdf"

    filename_parts = [date, doc_type]
    if person_name:
        filename_parts.append(person_name)
    if country:
        filename_parts.append(country)
    if issuer and issuer.lower() not in doc_type.lower():
        filename_parts.append(issuer)
    if reference:
        filename_parts.append(reference)
    smart_filename = "_".join(filter(None, (safe_part(x) for x in filename_parts)))[:220] + extension

    title_parts = [doc_type]
    if person_name:
        title_parts.append(person_name)
    if issuer and issuer.lower() not in doc_type.lower():
        title_parts.append(issuer)
    if reference:
        title_parts.append(reference)
    suggested_title = " - ".join(title_parts)

    confidence = 0.34
    confidence += min(0.30, len(found) * 0.09)
    confidence += 0.10 if issuer else 0
    confidence += 0.08 if date_found else 0
    confidence += 0.08 if reference else 0
    confidence += 0.10 if person_name else 0
    confidence += 0.05 if len(normalized) >= 120 else 0
    confidence = min(0.97, confidence)

    entities = {
        "issuer": issuer,
        "date": date if date_found else "",
        "reference": reference,
        "person_name": person_name,
        "country": country,
        "keywords": found,
        "source_filename": original_name,
    }
    return {
        "smart_filename": smart_filename,
        "suggested_title": suggested_title,
        "document_type": doc_type,
        "category": category,
        "country": country,
        "description_fa": f"نوع سند: {doc_type}؛ صاحب احتمالی سند: {person_name or 'نامشخص'}؛ صادرکننده احتمالی: {issuer or 'نامشخص'}؛ تاریخ تشخیص‌داده‌شده: {date if date_found else 'نامشخص'}.",
        "description_de": f"Dokumenttyp: {doc_type}; möglicher Aussteller: {issuer or 'unbekannt'}.",
        "ai_confidence": confidence,
        "extracted_entities": json.dumps(entities, ensure_ascii=False),
    }
