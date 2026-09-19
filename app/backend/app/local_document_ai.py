import json,os,requests
OLLAMA_URL=os.getenv("OLLAMA_URL","http://ollama:11434")
MODEL=os.getenv("DOCUMENT_AI_MODEL","qwen2.5:3b")
def analyze_document(ocr_text,filename):
 prompt="""Return JSON only. Classify this private document without inventing facts.
Keys: document_type,title,person_name,country,issuer,document_number,issue_date,expiry_date,confidence.
Use null when unknown. Dates YYYY-MM-DD. confidence: high, medium, low.
Prefer content over filename.
Filename: %s
OCR:
%s"""%(filename,(ocr_text or "")[:12000])
 try:
  r=requests.post(OLLAMA_URL+"/api/generate",json={"model":MODEL,"prompt":prompt,"stream":False,"format":"json"},timeout=180)
  r.raise_for_status(); x=json.loads(r.json().get("response","{}"))
  return x if isinstance(x,dict) else {}
 except Exception as e:
  return {"_error":str(e)[:500]}
