IR sync — phishing wave — notes (rough!!)
attendees: Lena (sec), Omar (sec), Kat (IT), Raj (comms)

what's happening
- users reporting emails "DocuSign: review payroll change" -> credential harvest page
- ~40 reports since 8am, 3 users confirmed entered creds

do right away (agreed)
- block sender domain + URL at email gateway + proxy  (Omar)
- force pw reset + revoke sessions for the 3 users, check MFA logs for new devices (Kat)
- pull all copies of the email from mailboxes (purge) (Omar)

how we tell if it's bad
- EDR: look for logins from new countries/devices for affected accts in last 24h
- if any of the 3 had admin rights -> treat as major, wake up the IC

impact
- possible payroll fraud if creds used on HR system; so far no access seen

comms
- Raj drafts all-staff "don't click" msg, sec reviews

TODO
- after: write up timeline + lessons learned within 3 days (Lena)
- ?? who decides if we notify the insurer — ask legal
