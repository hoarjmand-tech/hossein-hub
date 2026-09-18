import os,time,json,urllib.request,urllib.parse
from pathlib import Path
TOKEN=Path(os.getenv("TELEGRAM_BOT_TOKEN_FILE","/run/secrets/telegram_bot_token")).read_text().strip()
def sec(p):
 try:return Path(p).read_text().strip()
 except:return ""
ADMIN_ID=sec(os.getenv("TELEGRAM_ADMIN_ID_FILE","/run/secrets/telegram_admin_id"))
APP=os.getenv("TELEGRAM_APP_URL","https://hossein-hub.tailf8fccb.ts.net/telegram")
PROXY=os.getenv("TELEGRAM_PROXY","socks5h://host.docker.internal:10808")
# urllib has no SOCKS support; requests handles SOCKS via PySocks.
import requests
S=requests.Session();S.proxies.update({"http":PROXY,"https":PROXY})
API=f"https://api.telegram.org/bot{TOKEN}/"
def call(method,**data):
 r=S.post(API+method,json=data,timeout=45);r.raise_for_status();return r.json()
def keyboard():
 return {"inline_keyboard":[[{"text":"🚀 باز کردن Hossein Hub","web_app":{"url":APP}}]]}
def main():
 try:
  call("setMyCommands",commands=[{"command":"start","description":"باز کردن Hossein Hub"},{"command":"app","description":"Mini App"},{"command":"status","description":"وضعیت سیستم"}])
  call("setChatMenuButton",menu_button={"type":"web_app","text":"Hossein Hub","web_app":{"url":APP}})
 except Exception as e:print("telegram setup:",e,flush=True)
 offset=0
 while True:
  try:
   x=call("getUpdates",offset=offset,timeout=35,allowed_updates=["message"])
   for u in x.get("result",[]):
    offset=u["update_id"]+1;m=u.get("message") or {};chat=m.get("chat",{}).get("id");txt=m.get("text","")
    if chat and txt.split("@")[0]=="/id": call("sendMessage",chat_id=chat,text=f"Telegram ID: {chat}")
    elif chat and ADMIN_ID and str(chat)==ADMIN_ID and txt.split("@")[0] in ("/start","/app"):
     call("sendMessage",chat_id=chat,text="Hossein Hub\nدسترسی امن به داشبورد شخصی، آرشیو و سرویس‌ها.",reply_markup=keyboard())
    elif chat and ADMIN_ID and str(chat)==ADMIN_ID and txt.split("@")[0]=="/status":
     call("sendMessage",chat_id=chat,text="Hossein Hub فعال است. برای جزئیات Mini App را باز کن.",reply_markup=keyboard())
  except Exception as e:
   print("telegram:",type(e).__name__,str(e)[:180],flush=True);time.sleep(5)
if __name__=="__main__":main()
