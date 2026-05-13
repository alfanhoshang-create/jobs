"""
Send WhatsApp notification via CallMeBot
Usage: python scripts/notify_whatsapp.py <total_jobs> <page_url>

Setup (one time):
  1. Save +34 644 59 77 87 in your contacts as "CallMeBot"
  2. Send this WhatsApp message to that number: I allow callmebot to send me messages
  3. You'll receive your API key by WhatsApp
  4. Add it as GitHub Secret: CALLMEBOT_API_KEY
  5. Add your number as GitHub Secret: WHATSAPP_NUMBER (format: +33XXXXXXXXX)
"""

import sys, os, urllib.request, urllib.parse

def send(phone, api_key, message):
    encoded = urllib.parse.quote(message)
    url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={api_key}"
    req = urllib.request.Request(url, headers={"User-Agent": "JobBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = r.read().decode()
            print(f"CallMeBot response: {resp[:200]}")
            return True
    except Exception as e:
        print(f"WhatsApp error: {e}")
        return False

if __name__ == "__main__":
    total   = sys.argv[1] if len(sys.argv) > 1 else "?"
    page_url= sys.argv[2] if len(sys.argv) > 2 else "https://yourname.github.io/jobs/"

    phone   = os.environ.get("WHATSAPP_NUMBER", "")   # e.g. +33612345678
    api_key = os.environ.get("CALLMEBOT_API_KEY", "")

    if not phone or not api_key:
        print("⚠ WHATSAPP_NUMBER or CALLMEBOT_API_KEY not set — skipping notification")
        sys.exit(0)

    msg = (
        f"🦷 *Offres Assistant Dentaire — Mise à jour*\n\n"
        f"✅ {total} offres collectées sur 20 sites\n\n"
        f"👉 Voir la liste :\n{page_url}\n\n"
        f"_(Filtrez par source directement sur la page)_"
    )

    ok = send(phone, api_key, msg)
    sys.exit(0 if ok else 1)
