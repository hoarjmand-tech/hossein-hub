"""Integration smoke tests; use a temporary database, never live mailbox or Push calls."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['ARCHIVE_ROOT']=tempfile.mkdtemp(prefix='personal-test-')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main
from fastapi.testclient import TestClient

class PersonalInputsTest(unittest.TestCase):
    def test_private_input_lifecycle(self):
        with TestClient(main.app,base_url='https://testserver') as c:
            self.assertEqual(c.get('/api/personal/integrations').status_code,503)
            salt=b'0123456789012345';password='test-password-123'
            record={'salt':salt.hex(),'hash':hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()}
            passwordfile=main.ROOT/'personal-private/password.json'
            passwordfile.write_text(json.dumps(record))
            self.assertEqual(c.get('/api/personal/items').status_code,401)
            self.assertEqual(c.post('/api/personal/auth/login',json={'password':'bad'}).status_code,401)
            response=c.post('/api/personal/auth/login',json={'password':password})
            self.assertEqual(response.status_code,200)
            self.assertIn('HttpOnly',response.headers['set-cookie'])
            self.assertIn('Secure',response.headers['set-cookie'])
            self.assertEqual(c.post('/api/personal/items',headers={'Origin':'https://evil.test'},json={'title':'bad'}).status_code,403)
            self.assertEqual(c.get('/api/personal/integrations').status_code,200)
            voice=c.post('/api/personal/voice',files={'file':('sample.wav',b'RIFF1234WAVEfmt ','audio/wav')})
            self.assertEqual(voice.status_code,200,voice.text)
            self.assertIn('capture',voice.json())
            vid=voice.json()['voice_id']
            self.assertEqual(c.get('/api/personal/voice/'+vid).status_code,200)
            self.assertTrue((main.ROOT/'personal-private/voice'/vid).exists())
            self.assertEqual(c.post('/api/personal/voice',files={'file':('bad.html',b'<script>','text/html')}).status_code,400)
            self.assertEqual(c.post('/api/personal/integrations/mail',json={'host':'localhost','username':'x','password':'x'}).status_code,400)
            with patch('personal_integrations.imaplib.IMAP4_SSL',FakeIMAP):
                response=c.post('/api/personal/integrations/mail',json={'host':'imap.gmail.com','username':'owner@example.com','password':'app-password'})
                self.assertEqual(response.status_code,200,response.text)
                self.assertNotIn(b'app-password',(main.ROOT/'personal-private/settings.enc').read_bytes())
                self.assertNotIn('password',c.get('/api/personal/integrations').text)
                self.assertEqual(c.post('/api/personal/integrations/mail/sync',json={}).json()['imported'],1)
                self.assertEqual(c.post('/api/personal/integrations/mail/sync',json={}).json()['imported'],0)
            sub={'endpoint':'https://web.push.apple.com/test-endpoint','keys':{'p256dh':'test','auth':'test'}}
            self.assertEqual(c.post('/api/personal/push/subscribe',json={'subscription':{'endpoint':'http://127.0.0.1:22'}}).status_code,400)
            self.assertEqual(c.post('/api/personal/push/subscribe',json={'subscription':sub,'contact':'owner@example.com'}).status_code,200)
            with patch('personal_integrations.webpush') as push:
                self.assertEqual(c.post('/api/personal/push/test',json={'endpoint':sub['endpoint']}).status_code,200)
                self.assertEqual(push.call_count,1)
            self.assertEqual(c.get('/personal/widget').status_code,200)
            self.assertEqual(c.get('/personal/manifest.webmanifest').json()['start_url'],'/personal')
            self.assertEqual(c.get('/personal/sw.js').status_code,200)
            self.assertEqual(c.get('/personal/icon-192.png').status_code,200)
            # Changing the password invalidates previously issued signed cookies.
            record['hash']='newhash';passwordfile.write_text(json.dumps(record))
            self.assertEqual(c.get('/api/personal/items').status_code,401)

class FakeIMAP:
    def __init__(self,*args,**kwargs): pass
    def login(self,*args): return 'OK',[]
    def select(self,mailbox,readonly):
        assert readonly is True
        return 'OK',[]
    def uid(self,command,*args):
        if command=='search': return 'OK',[b'42']
        assert 'BODY.PEEK' in args[1]
        return 'OK',[(b'42',b'Subject: Insurance reply\r\nFrom: insurance@example.com\r\nMessage-ID: <test42>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nPlease reply next week.')]
    def response(self,name): return name,[b'1']
    def logout(self): pass

if __name__=='__main__': unittest.main()
