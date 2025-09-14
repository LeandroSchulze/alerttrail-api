import imaplib, email
M = imaplib.IMAP4_SSL(imap_host, imap_port)
M.login(email, password)
M.logout()
except Exception as e:
raise HTTPException(400, f"No se pudo conectar: {e}")
return {"status":"ok"}


@router.post('/scan', response_class=HTMLResponse)
async def scan(request: Request, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
acc = db.query(MailAccount).filter(MailAccount.user_id==user_id).first()
if not acc:
raise HTTPException(400, 'Primero debes vincular tu casilla en /mail/connect')


pwd = fernet_decrypt(acc.enc_password)
items = []


def _decode(s):
if not s: return ''
parts = decode_header(s)
out = ''
for t, enc in parts:
if isinstance(t, bytes):
out += t.decode(enc or 'utf-8', errors='ignore')
else:
out += t
return out


try:
M = imaplib.IMAP4_SSL(acc.imap_host, acc.imap_port)
M.login(acc.email, pwd)
M.select('INBOX')
typ, data = M.search(None, 'ALL')
ids = data[0].split()[-30:] # últimos 30
for uid in reversed(ids):
typ, msg_data = M.fetch(uid, '(RFC822)')
msg = email.message_from_bytes(msg_data[0][1])
sender = _decode(msg.get('From'))
subject = _decode(msg.get('Subject'))
# Reglas simples
text = subject.lower()
verdict = 'SAFE'
red_flags = ['urgent', 'verify account', 'password', 'bitcoin', 'transfer', 'invoice', 'factura', 'pago', 'suspendido', 'suspendida', 'confirmar']
if any(k in text for k in red_flags):
verdict = 'SUSPICIOUS'
items.append({'sender': sender, 'subject': subject, 'verdict': verdict})
db.add(MailScan(user_id=user_id, sender=sender, subject=subject, verdict=verdict))
db.commit()
M.logout()
except Exception as e:
raise HTTPException(400, f"Fallo al escanear: {e}")


summary = f"Escaneados {len(items)} correos. Sospechosos: {sum(1 for i in items if i['verdict']=='SUSPICIOUS')}"
return templates.TemplateResponse('mail_scan_result.html', { 'request': request, 'summary': summary, 'items': items })
