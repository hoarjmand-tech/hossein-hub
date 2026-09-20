import json
import os
import tempfile
import time
from pathlib import Path

import requests

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
API=os.getenv("ARCHIVE_API","http://archive:8080").rstrip("/")
PUBLIC_URL=os.getenv("PUBLIC_BASE_URL","http://192.168.1.35:8080").rstrip("/")
MINI_APP_URL=(os.getenv("TELEGRAM_MINI_APP_URL","").strip() or f"{PUBLIC_URL}/telegram").rstrip("/")
ALLOWED={x.strip() for x in os.getenv("TELEGRAM_ALLOWED_USERS","").split(",") if x.strip()}
TG=f"https://api.telegram.org/bot{TOKEN}"
FILE_API=f"https://api.telegram.org/file/bot{TOKEN}"


def allowed(message):
    user=str((message.get("from") or {}).get("id", ""))
    return not ALLOWED or user in ALLOWED


def send(chat_id,text,reply_markup=None):
    payload={"chat_id":chat_id,"text":text,"parse_mode":"HTML","disable_web_page_preview":True}
    if reply_markup:
        payload["reply_markup"]=json.dumps(reply_markup,ensure_ascii=False)
    return requests.post(f"{TG}/sendMessage",data=payload,timeout=60).json()


def keyboard():
    rows=[]
    if MINI_APP_URL.startswith("https://"):
        rows.append([{"text":"📚 بازکردن Mini App","web_app":{"url":MINI_APP_URL}}])
    rows.extend([["📥 افزودن سند","🔎 جست‌وجو"],["📊 آمار","🌐 باز کردن آرشیو"]])
    return {"keyboard":rows,"resize_keyboard":True}


def bot_api(method,payload):
    result=requests.post(f"{TG}/{method}",json=payload,timeout=30).json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {result.get('description','unknown error')}")
    return result


def setup_bot():
    commands=[
        {"command":"start","description":"شروع و نمایش منو"},
        {"command":"app","description":"بازکردن آرشیو هوشمند"},
        {"command":"search","description":"جست‌وجو در اسناد"},
        {"command":"stats","description":"آمار آرشیو"},
    ]
    bot_api("setMyCommands",{"commands":commands})
    if MINI_APP_URL.startswith("https://"):
        menu={"type":"web_app","text":"آرشیو هوشمند","web_app":{"url":MINI_APP_URL}}
        bot_api("setChatMenuButton",{"menu_button":menu})
        print(json.dumps({"event":"telegram_mini_app_registered","url":MINI_APP_URL},ensure_ascii=False),flush=True)
    else:
        print(json.dumps({"event":"telegram_mini_app_waiting_for_https","url":MINI_APP_URL},ensure_ascii=False),flush=True)


def stats(chat_id):
    data=requests.get(f"{API}/api/stats",timeout=30).json()
    send(chat_id,
         f"📊 <b>وضعیت آرشیو</b>\n\n"
         f"اسناد: {data.get('documents',0)}\n"
         f"در صف OCR: {data.get('processing',0)}\n"
         f"خطای OCR: {data.get('failed',0)}\n"
         f"ورودی اسکنر: {data.get('scanner',0)}\n"
         f"ورودی تلگرام: {data.get('telegram',0)}")


def search(chat_id,query):
    data=requests.get(f"{API}/api/documents",params={"q":query},timeout=30).json()
    items=(data.get("items") or [])[:10]
    if not items:
        send(chat_id,"سندی پیدا نشد.")
        return
    lines=[f"🔎 <b>نتیجه جست‌وجو برای:</b> {query}"]
    for index,item in enumerate(items,1):
        lines.append(f"\n{index}. <a href=\"{PUBLIC_URL}/api/documents/{item['id']}/file\">{item['title']}</a>")
    send(chat_id,"".join(lines))


def download_telegram_file(file_id,name):
    info=requests.get(f"{TG}/getFile",params={"file_id":file_id},timeout=30).json()
    if not info.get("ok"):
        raise RuntimeError("Telegram file metadata failed")
    remote=info["result"]["file_path"]
    suffix=Path(name).suffix or Path(remote).suffix or ".bin"
    target=Path(tempfile.gettempdir())/f"telegram-{int(time.time()*1000)}{suffix}"
    with requests.get(f"{FILE_API}/{remote}",stream=True,timeout=180) as response:
        response.raise_for_status()
        with target.open("wb") as output:
            for chunk in response.iter_content(1024*1024):
                output.write(chunk)
    return target


def ingest_file(chat_id,file_id,name):
    path=download_telegram_file(file_id,name)
    try:
        with path.open("rb") as handle:
            response=requests.post(
                f"{API}/api/documents/upload",
                files={"files":(name,handle,"application/octet-stream")},
                headers={"X-Archive-Source":"telegram"},
                timeout=300,
            )
        response.raise_for_status()
        item=(response.json().get("items") or [{}])[0]
        if item.get("duplicate"):
            send(chat_id,"♻️ این سند قبلاً در آرشیو ثبت شده است.")
        else:
            send(chat_id,"✅ سند دریافت شد و برای OCR و دسته‌بندی وارد صف شد.")
    finally:
        path.unlink(missing_ok=True)


def handle(message):
    chat_id=(message.get("chat") or {}).get("id")
    if not chat_id:
        return
    if not allowed(message):
        send(chat_id,"⛔ دسترسی شما به این آرشیو مجاز نیست.")
        return
    text=(message.get("text") or "").strip()
    if text in ("/start","/help"):
        send(chat_id,"<b>بات آرشیو هوشمند حسین</b>\n\nMini App را باز کنید یا فایل را مستقیماً برای OCR ارسال کنید.",keyboard())
    elif text in ("/stats","📊 آمار"):
        stats(chat_id)
    elif text in ("🌐 باز کردن آرشیو","/app"):
        if MINI_APP_URL.startswith("https://"):
            send(chat_id,"📚 آرشیو کامل را داخل Telegram باز کنید:",{"inline_keyboard":[[{"text":"بازکردن آرشیو هوشمند","web_app":{"url":MINI_APP_URL}}]]})
        else:
            send(chat_id,"⚠️ آدرس HTTPS عمومی Mini App هنوز تنظیم نشده است.")
    elif text in ("📥 افزودن سند",):
        send(chat_id,"فایل PDF یا تصویر سند را همین‌جا ارسال کنید.")
    elif text in ("🔎 جست‌وجو",):
        send(chat_id,"عبارت را به شکل زیر بفرستید:\n<code>/search عبارت موردنظر</code>")
    elif text.startswith("/search "):
        search(chat_id,text[8:].strip())
    elif message.get("document"):
        doc=message["document"]
        ingest_file(chat_id,doc["file_id"],doc.get("file_name") or "telegram-document.pdf")
    elif message.get("photo"):
        photo=message["photo"][-1]
        ingest_file(chat_id,photo["file_id"],f"telegram-photo-{photo['file_unique_id']}.jpg")
    elif text:
        search(chat_id,text)


def main():
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN is empty; Telegram module is idle.",flush=True)
        while True:
            time.sleep(3600)
    offset=0
    setup_bot()
    print("Telegram archive bot started",flush=True)
    while True:
        try:
            response=requests.get(f"{TG}/getUpdates",params={"timeout":45,"offset":offset},timeout=60).json()
            for update in response.get("result",[]):
                offset=max(offset,update["update_id"]+1)
                handle(update.get("message") or {})
        except Exception as exc:
            print(json.dumps({"event":"telegram_error","error":str(exc)},ensure_ascii=False),flush=True)
            time.sleep(5)


if __name__=="__main__":
    main()
