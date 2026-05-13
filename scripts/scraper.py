"""
Dental Job Scraper — Assistant Dentaire
Updated: Fixed Apify 404s + better error handling
"""

import os, json, time, hashlib, re
from datetime import datetime, timezone
import urllib.request, urllib.parse, urllib.error

# ──────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────
KEYWORDS       = "assistant dentaire"
LOCATION       = ""          
MAX_PER_SOURCE = 3000        

FT_CLIENT_ID     = os.environ.get("FT_CLIENT_ID", "")
FT_CLIENT_SECRET = os.environ.get("FT_CLIENT_SECRET", "")
ADZUNA_APP_ID    = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY   = os.environ.get("ADZUNA_APP_KEY", "")
JOOBLE_API_KEY   = os.environ.get("JOOBLE_API_KEY", "")
APIFY_API_KEY    = os.environ.get("APIFY_API_KEY", "")

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ──────────────────────────────────────────
# HELPERS (unchanged)
# ──────────────────────────────────────────
def esc(s):
    return str(s or "").strip()

def uid(source, url, title):
    raw = f"{source}|{url}|{title}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def http_get(url, headers=None, timeout=20, return_headers=False):
    merged = {"User-Agent": _DEFAULT_UA,
              "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
              "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}
    if headers:
        merged.update(headers)

    req = urllib.request.Request(url, headers=merged)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            resp_headers = dict(r.headers)
            content = r.read().decode("utf-8", errors="replace")
            if status not in (200, 206):
                print(f"  ⚠ HTTP {status} from {url[:80]}")
            if return_headers:
                return content, resp_headers
            return content
    except Exception as e:
        print(f"  ❌ GET error {url[:80]}: {e}")
        return ("", {}) if return_headers else ""

def http_post(url, data, headers=None, timeout=60):
    body = json.dumps(data).encode()
    h = {"Content-Type": "application/json", "User-Agent": _DEFAULT_UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP {e.code} POST error: {url[:80]}")
        return ""
    except Exception as e:
        print(f"  ❌ POST error {url[:80]}: {e}")
        return ""

def parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None

def normalize(source, title, company, location, contract, salary,
              date_str, description, apply_url, extra=None):
    return {
        "id":                 uid(source, apply_url, title),
        "source":             esc(source),
        "intitule":           esc(title),
        "entreprise":         {"nom": esc(company) or "Confidentiel"},
        "lieuTravail":        {"libelle": esc(location)},
        "typeContratLibelle": esc(contract),
        "salaire":            {"libelle": esc(salary)},
        "dateCreation":       esc(date_str),
        "description":        esc(description),
        "origineOffre":       {"urlOrigine": esc(apply_url)},
        "extra":              extra or {},
    }

def make_direct_link(source, url, note=""):
    return normalize(
        source      = source,
        title       = f"Voir les offres '{KEYWORDS}' sur {source}",
        company     = "",
        location    = "France",
        contract    = "",
        salary      = "",
        date_str    = "",
        description = note or f"Cliquez pour voir toutes les offres sur {source}.",
        apply_url   = url,
    )

# ──────────────────────────────────────────
# UPDATED APIFY RUNNER (Critical Fix)
# ──────────────────────────────────────────
def fetch_via_apify(actor_id, run_input, source_name, mapper_fn, timeout_secs=120):
    if not APIFY_API_KEY:
        print("  ⚠ APIFY_API_KEY not set")
        return []

    # FIXED: Use ~ instead of /
    safe_actor = actor_id.replace('/', '~')
    qs = urllib.parse.urlencode({
        "token":   APIFY_API_KEY,
        "timeout": timeout_secs,
        "memory":  256,
    })
    url = f"https://api.apify.com/v2/acts/{safe_actor}/run-sync-get-dataset-items?{qs}"
    
    print(f"  → Calling Apify actor: {actor_id}")
    text = http_post(url, run_input, timeout=timeout_secs + 10)
    data = parse_json(text)

    if not data or not isinstance(data, list):
        print(f"  ⚠ No data from Apify for {source_name}")
        if text and len(text) < 800:
            print(f"  Response: {text[:600]}...")
        return []

    jobs = []
    for o in data[:MAX_PER_SOURCE]:
        j = mapper_fn(o)
        if j:
            jobs.append(j)
    print(f"  ✓ {len(jobs)} jobs from {source_name}")
    return jobs

# ──────────────────────────────────────────
# FRANCE TRAVAIL (unchanged - already working well)
# ──────────────────────────────────────────
def fetch_france_travail():
    print("🔍 France Travail...")
    # ... (your original France Travail function - keep it as is)
    # I'll keep it short here for space, but copy your full original function
    jobs = []
    if not FT_CLIENT_ID or not FT_CLIENT_SECRET:
        print("  ⚠ FT keys not set — skipping")
        return jobs

    # [Paste your full original fetch_france_travail() code here]
    # It's long, so just replace this comment with your working version
    # (the one that already returns 560 jobs)

    token_url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
    # ... rest of your original code ...

    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# ADZUNA + JOOBLE (with better logging)
# ──────────────────────────────────────────
def fetch_adzuna():
    print("🔍 Adzuna...")
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("  ⚠ ADZUNA keys not set")
        return []
    
    jobs = []
    page = 1
    while len(jobs) < MAX_PER_SOURCE:
        qs = urllib.parse.urlencode({
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "results_per_page": 50,
            "what": KEYWORDS,
            "where": "France",
        })
        url = f"https://api.adzuna.com/v1/api/jobs/fr/search/{page}?{qs}"
        text = http_get(url)
        data = parse_json(text)
        
        if not data:
            print("  ❌ Adzuna: Invalid JSON response")
            break
            
        results = data.get("results", [])
        if not results and page == 1:
            print(f"  ⚠ Adzuna returned 0 results (check if your keys support France)")
        
        for o in results:
            # ... your original normalize logic ...
            pass   # I'll let you keep your original loop

        page += 1
        if len(results) < 50:
            break
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

def fetch_jooble():
    print("🔍 Jooble...")
    # Keep your original or comment out if 403 persists
    return []   # temporarily disabled due to 403

# Paste your original fetch_indeed, fetch_glassdoor, fetch_linkedin here and replace with the updated ones I gave you earlier.

# (For brevity, I suggest you take the three updated functions from my previous message)

# ──────────────────────────────────────────
# MAIN + other functions remain the same
# ──────────────────────────────────────────

# ... rest of your script (SCRAPERS list, main(), etc.)

if __name__ == "__main__":
    main()
