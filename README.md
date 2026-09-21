# Hossein Hub Archive 4.6

## امکانات نسخه 4.6

- تاریخ صدور و انقضای مدارک و فیلتر وضعیت اعتبار
- داشبورد هشدار مدارک منقضی یا رو به انقضا
- پرونده کامل هر شخص یا سازمان و آمار مدارک آن
- چک‌لیست مدارک لازم و گزارش خودکار مدارک ناقص
- نسخه‌بندی امن اسناد؛ فایل قبلی هنگام جایگزینی حفظ می‌شود
- دسترسی به نسخه‌های قدیمی و ثبت توضیح برای هر نسخه
- پشتیبانی همین امکانات در پنل وب و Telegram Mini App

## انتشار امن Telegram Mini App با Cloudflare Tunnel

1. در Cloudflare Zero Trust یک Tunnel بسازید.
2. Public Hostname را روی `archive.arjmand.xyz` و Service را روی
   `http://telegram-gateway:8081` قرار دهید.
3. روی سرور `sudo bash setup-telegram.sh` را اجرا کنید و Bot Token، Telegram
   User ID، آدرس `https://archive.arjmand.xyz/telegram` و Tunnel Token را وارد کنید.

Gateway عمومی فقط Mini App، API امضاشده تلگرام و لینک‌های اشتراک را عبور
می‌دهد؛ پنل مدیریتی اصلی روی پورت 8188 باقی می‌ماند.

نسخه ۴.۵ شامل پرونده اشخاص و سازمان‌ها، نوع مدرک و کشور، فیلترهای ترکیبی، نام پیشنهادی OCR قابل ویرایش، لینک مستقیم دانلود و فونت فارسی محلی است. این امکانات در پنل وب و Mini App تلگرام در دسترس‌اند.

سامانه ماژولار آرشیو هوشمند اسناد با قابلیت‌های زیر:

- آپلود وب، Drag & Drop و نمایش PDF یا تصویر
- OCR فارسی، انگلیسی و آلمانی
- جست‌وجوی متن کامل، دسته‌بندی و نام‌گذاری هوشمند
- تشخیص فایل تکراری با SHA-256
- پوشه ورودی خودکار برای اسکنرها
- بات تلگرام برای آپلود، آمار و جست‌وجو
- پیش‌نمایش، اشتراک موقت، دانلود و خروجی گروهی
- گزارش فعالیت، وضعیت پردازش و فضای ذخیره‌سازی
- رابط جمع‌وجور و واکنش‌گرا، منوی مینی و تغییر امن نام فایل
- پیش‌نمایش کوچک داخل قاب و نام‌گذاری خودکار فایل با OCR فارسی، آلمانی و انگلیسی
- تشخیص صاحب سند از نام و نام خانوادگی فارسی، انگلیسی، آلمانی و MRZ گذرنامه
- Telegram Mini App کامل برای جست‌وجو، آپلود، پیش‌نمایش، ویرایش، OCR، نام‌گذاری، دانلود و اشتراک
- حفظ فایل اصلی و Migration خودکار دیتابیس

## Deploy

```bash
cd /opt/hossein-hub && git pull origin main && sudo bash deploy.sh
```

پنل داخلی: `http://192.168.1.35:8080`

پوشه ورودی اسکنر: `/opt/hossein-hub/scanner_inbox`

فایل‌های پردازش‌شده و خطادار به‌ترتیب به `scanner_processed` و
`scanner_errors` منتقل می‌شوند.

## Telegram

مقادیر `TELEGRAM_BOT_TOKEN` و `TELEGRAM_ALLOWED_USERS` را در فایل `.env`
قرار دهید و دوباره `sudo bash deploy.sh` را اجرا کنید. تا پیش از ثبت Token،
ماژول تلگرام در حالت انتظار باقی می‌ماند.

راه‌اندازی بات بدون ویرایش دستی فایل:

```bash
sudo bash setup-telegram.sh BOT_TOKEN TELEGRAM_USER_ID
```

برای Mini App باید یک آدرس عمومی HTTPS به مسیر `/telegram` متصل باشد و سپس
آدرس کامل آن در `TELEGRAM_MINI_APP_URL` ثبت شود. نمونه:

```bash
sudo bash setup-telegram.sh BOT_TOKEN TELEGRAM_USER_ID https://archive.example.com/telegram
```

بات هنگام شروع، دکمه منوی Mini App را به‌صورت خودکار با Bot API ثبت می‌کند.
درخواست‌های Mini App با امضای `Telegram.WebApp.initData` و فهرست User IDهای
مجاز کنترل می‌شوند.

برای انتشار امن، دامنه یا Cloudflare Tunnel را به پورت `8081` سرویس
`telegram-gateway` متصل کنید؛ پورت `8080` فقط برای پنل داخلی شبکه است. Gateway
تنها Mini App، API امضاشده Telegram و لینک‌های اشتراک توکنی را منتشر می‌کند.

بررسی کامل سلامت سامانه:

```bash
sudo bash health-check.sh
```
