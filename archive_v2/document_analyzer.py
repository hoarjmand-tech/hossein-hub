import json
import re
from datetime import datetime
from pathlib import Path


RULES = [
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
    extension = Path(original_name or "").suffix.lower()
    if extension not in {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
        extension = ".pdf"

    filename_parts = [date, doc_type]
    if issuer and issuer.lower() not in doc_type.lower():
        filename_parts.append(issuer)
    if reference:
        filename_parts.append(reference)
    smart_filename = "_".join(filter(None, (safe_part(x) for x in filename_parts)))[:220] + extension

    title_parts = [doc_type]
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
    confidence += 0.05 if len(normalized) >= 120 else 0
    confidence = min(0.97, confidence)

    entities = {
        "issuer": issuer,
        "date": date if date_found else "",
        "reference": reference,
        "keywords": found,
        "source_filename": original_name,
    }
    return {
        "smart_filename": smart_filename,
        "suggested_title": suggested_title,
        "document_type": doc_type,
        "category": category,
        "description_fa": f"نوع سند: {doc_type}؛ صادرکننده احتمالی: {issuer or 'نامشخص'}؛ تاریخ تشخیص‌داده‌شده: {date if date_found else 'نامشخص'}.",
        "description_de": f"Dokumenttyp: {doc_type}; möglicher Aussteller: {issuer or 'unbekannt'}.",
        "ai_confidence": confidence,
        "extracted_entities": json.dumps(entities, ensure_ascii=False),
    }
