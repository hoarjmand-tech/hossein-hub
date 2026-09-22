"""Run interactively inside the archive container; passwords never enter shell history."""
import getpass
import hashlib
import json
import os
import secrets
from pathlib import Path
root=Path(os.getenv('ARCHIVE_ROOT','/data'))/'personal-private'
root.mkdir(mode=0o700,exist_ok=True)
a=getpass.getpass('New personal password (12+ characters): ')
b=getpass.getpass('Repeat password: ')
if a!=b or len(a)<12:
    raise SystemExit('Passwords must match and contain at least 12 characters.')
salt=secrets.token_bytes(16)
value={'salt':salt.hex(),'hash':hashlib.scrypt(a.encode(),salt=salt,n=16384,r=8,p=1).hex()}
fd=os.open(root/'password.json',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,'w') as f: json.dump(value,f)
# Password changes invalidate existing sessions without touching the encrypted IMAP settings.
print('Personal lock enabled. Open the HTTPS personal page to sign in.')
