# Personal assistant: mail, voice and notifications

This update extends `/personal`; `/personal/widget` is a compact web dashboard, not a native iOS widget extension.

## Deploy

Run in `/opt/hossein-hub`:

```sh
git pull --ff-only origin main
sudo docker compose up -d --build --no-deps archive
sudo docker exec -it hossein-archive python setup_personal_lock.py
```

The final command prompts twice for a password of at least 12 characters. It protects personal pages and all `/api/personal/*` content. Password reset uses the same command and invalidates existing sessions. It does not change the existing archive's authentication model. Personal cookies are HTTPS-only; use your working HTTPS URL, e.g. `https://hossein-hub.tailf8fccb.ts.net/personal`. This update does not create or repair HTTPS hosting.

## Enable from Safari

1. Open the HTTPS personal URL and sign in.
2. Open **اتصال‌ها و اعلان**.
3. To use Push on iPhone, add the page through **Share → Add to Home Screen** and reopen from its icon. In settings provide a contact email, tap **اجازه اعلان**, then **اعلان آزمایشی**. Browser/system permission must be granted on the device; server code cannot grant it.
4. Each device subscribes separately. **خاموش‌کردن این دستگاه** removes that device's subscription. Notifications contain generic text, not private email or task titles.
5. Due tasks and waiting items' follow-up times are checked about every 15 seconds while the server is running. One successful send is recorded per device/item/date/type. Rejected expired subscriptions are removed; transient failures retry. Delivery time is ultimately controlled by the browser, OS, network and Push service. All-day deadlines become due at midnight; enter a time when a precise reminder is needed.

## Email

Supported IMAP hosts: Gmail, Yahoo, iCloud. Enable IMAP and create an app-specific password in the provider's account settings, when available. Paste it into this app's settings, never a chat or a repository. Some accounts disallow app passwords; OAuth-only providers, including modern Outlook configurations, are not supported in this release.

**آزمایش و اتصال** verifies read-only Inbox access before saving credentials. **دریافت اکنون** imports immediately. Otherwise, the server polls every five minutes. It inspects the latest 30 Inbox messages from the past seven days, records UIDVALIDITY/UID to avoid normal repeat imports, reads with BODY.PEEK, and never sends, moves, deletes, or marks mail as read. Plain text is capped at 4,000 characters, message fetches at 256 KiB; attachments and HTML rendering are deliberately not imported. Imported emails need manual triage; this release does not infer tasks/deadlines from them.

Disconnect deletes the saved mailbox credentials; already imported items remain until the owner deletes them. Errors shown to clients do not include credentials or raw provider responses. Mailbox credentials are encrypted using a separate server-side key with restricted permissions. This is encryption at rest, not protection from an administrator who can read both the key and data.

## Voice

**یادداشت صوتی** supports explicit microphone permission, recording up to five minutes, playback before save and audio-file upload up to 20 MiB. Audio is kept on the same server as the archive; no external transcription service receives it. Open the saved item to play it. Deleting the item deletes its stored recording. Automatic transcription and action extraction are not enabled.

## Data and backup

The existing SQLite database stores items, import identifiers and push subscriptions. `archive_data/personal-private/` stores the password hash, encryption key, encrypted mailbox settings, VAPID private key and recordings. Back up the database and this directory together with the archive. Preserve file permissions. Never commit this directory or send it as troubleshooting output. The service worker does not cache private content; offline editing is not supported.

The existing desktop/archive endpoints retain their previous exposure. This update adds an owner lock for the personal assistant only; it is not an authentication retrofit for the entire archive.

## Validation

```sh
python -m pip install -r archive_v2/requirements.txt httpx
python -m unittest discover -s archive_v2/tests -v
```

Tests use a temporary database and fake IMAP/Push transports: password/login/session invalidation, CSRF rejection, voice save/play/delete, MIME rejection, private-network endpoint rejection, read-only mail import and deduplication, encrypted credential persistence, Push registration/test, manifest, icon and widget routes. Real mailbox connectivity and delivery on the user's iPhone require their own credentials and device permission.
