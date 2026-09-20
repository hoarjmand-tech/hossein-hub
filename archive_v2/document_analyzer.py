import re
import json
from datetime import datetime


RULES = [
    ("Insurance","insurance",["arag","versicherung","versicherungsbestätigung","rechtsschutz"]),
    ("Residence","legal",["ma35","niederlassungsbewilligung","aufenthaltstitel","bescheid"]),
    ("Bank","finance",["kontoauszug","bank","sparkasse","erste","mittelherkunft"]),
    ("Contract","contract",["vertrag","contract","agreement"]),
    ("Invoice","invoice",["rechnung","invoice","faktura"]),
]


def clean(text):
    return re.sub(r"\s+"," ",text or "").lower()


def analyze_document(text, original_name=""):

    t = clean(text)

    doc_type="Document"
    category="other"
    confidence=0.4
    found=[]

    for name,cat,keys in RULES:
        hits=[k for k in keys if k in t]

        if len(hits)>len(found):
            found=hits
            doc_type=name
            category=cat
            confidence=min(0.95,0.55+len(hits)*0.12)


    issuer=""

    for x in [
        "ARAG SE",
        "MA35",
        "Erste Bank",
        "Sparkasse",
        "ÖGK"
    ]:
        if x.lower() in t:
            issuer=x
            break


    date=datetime.now().strftime("%Y-%m-%d")

    m=re.search(r"\d{2}[./-]\d{2}[./-]\d{4}",text or "")
    if m:
        date=m.group().replace(".","-")


    filename=f"{date}_{issuer or doc_type}_{doc_type}.pdf"

    filename=re.sub(
        r"[^a-zA-Z0-9äöüÄÖÜß_-]",
        "_",
        filename
    )


    return {

        "smart_filename":filename,

        "document_type":doc_type,

        "category":category,

        "description_fa":
        f"این فایل یک سند از نوع {doc_type} است. "
        f"صادرکننده احتمالی: {issuer or 'نامشخص'}."
        ,

        "description_de":
        f"Dieses Dokument ist ein {doc_type}. "
        f"Möglicher Aussteller: {issuer or 'unbekannt'}.",

        "ai_confidence":confidence,

        "extracted_entities":json.dumps(
            {
                "issuer":issuer,
                "keywords":found
            },
           ensure_ascii=False
        )
    }
