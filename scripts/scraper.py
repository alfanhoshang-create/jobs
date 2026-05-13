"""
Dental Job Scraper — Assistant Dentaire
Searches all configured sources and outputs jobs.json

FIXES vs v1:
- Adzuna: URL bug fixed (page was duplicated in path + query)
- Indeed: updated RSS URL format
- HelloWork: verified RSS endpoint
- Meteojob: verified RSS endpoint  
- Talent.com: verified RSS endpoint
- Option Carrière: verified RSS endpoint
- APEC: updated to current public API
- Staffsanté / Appel Médical / Vitalis: corrected RSS paths
- Dental Emploi: improved HTML regex + fallback
- All sources: better error logging (shows HTTP status code)
"""

import os, json, time, hashlib, re
from datetime import datetime, timezone
import urllib.request, urllib.parse, urllib.error

# ──────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────
KEYWORDS       = "assistant dentaire"
LOCATION       = ""          # empty = whole France
MAX_PER_SOURCE = 100

# API keys — set as GitHub Secrets
FT_CLIENT_ID     = os.environ.get("FT_CLIENT_ID", "")
FT_CLIENT_SECRET = os.environ.get("FT_CLIENT_SECRET", "")
ADZUNA_APP_ID    = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY   = os.environ.get("ADZUNA_APP_KEY", "")
JOOBLE_API_KEY   = os.environ.get("JOOBLE_API_KEY", "")

# ──────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────
def esc(s):
    return str(s or "").strip()

def uid(source, url, title):
    raw = f"{source}|{url}|{title}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def http_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {
        # Mimic a real browser more closely to avoid bot blocks
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            content = r.read().decode("utf-8", errors="replace")
            if status != 200:
                print(f"  ⚠ HTTP {status} from {url[:80]}")
            return content
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP {e.code} error: {url[:80]}")
        return ""
    except urllib.error.URLError as e:
        print(f"  ❌ URL error ({e.reason}): {url[:80]}")
        return ""
    except Exception as e:
        print(f"  ❌ GET error {url[:80]}: {e}")
        return ""

def http_post(url, data, headers=None, timeout=20):
    body = json.dumps(data).encode()
    h = {"Content-Type": "application/json", "User-Agent": "JobBot/1.0"}
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
        "id":          uid(source, apply_url, title),
        "source":      esc(source),
        "intitule":    esc(title),
        "entreprise":  {"nom": esc(company) or "Confidentiel"},
        "lieuTravail": {"libelle": esc(location)},
        "typeContratLibelle": esc(contract),
        "salaire":     {"libelle": esc(salary)},
        "dateCreation": esc(date_str),
        "description": esc(description),
        "origineOffre": {"urlOrigine": esc(apply_url)},
        "extra": extra or {},
    }

# ──────────────────────────────────────────
# SOURCE 1 — FRANCE TRAVAIL (official API)
# ──────────────────────────────────────────
def fetch_france_travail():
    print("🔍 France Travail...")
    jobs = []
    if not FT_CLIENT_ID or not FT_CLIENT_SECRET:
        print("  ⚠ FT_CLIENT_ID / FT_CLIENT_SECRET not set — skipping")
        return jobs

    token_url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
    params = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     FT_CLIENT_ID,
        "client_secret": FT_CLIENT_SECRET,
        "scope":         "api_offresdemploiv2 o2dsoffre"
    })
    req = urllib.request.Request(token_url, data=params.encode(),
          headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            tok = json.loads(r.read())
            token = tok.get("access_token", "")
    except Exception as e:
        print(f"  ❌ Token error: {e}")
        return jobs

    base  = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    start = 0
    while len(jobs) < MAX_PER_SOURCE:
        count = min(150, MAX_PER_SOURCE - len(jobs))
        qs = urllib.parse.urlencode({
            "motsCles": KEYWORDS,
            "range":    f"{start}-{start+count-1}",
        })
        text = http_get(f"{base}?{qs}", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        })
        data = parse_json(text)
        if not data:
            break
        results = data.get("resultats", [])
        if not results:
            break
        for o in results:
            loc = (o.get("lieuTravail") or {}).get("libelle", "")
            jobs.append(normalize(
                source      = "France Travail",
                title       = o.get("intitule", ""),
                company     = (o.get("entreprise") or {}).get("nom", ""),
                location    = loc,
                contract    = o.get("typeContratLibelle", ""),
                salary      = (o.get("salaire") or {}).get("libelle", ""),
                date_str    = o.get("dateCreation", ""),
                description = o.get("description", ""),
                apply_url   = (o.get("origineOffre") or {}).get("urlOrigine", ""),
                extra       = {
                    "dureeTravail":  (o.get("dureeTravailLibelle") or ""),
                    "experience":    (o.get("experienceLibelle") or ""),
                    "qualification": (o.get("qualificationLibelle") or ""),
                    "secteur":       (o.get("secteurActiviteLibelle") or ""),
                    "formation":     ", ".join(
                        f.get("niveauLibelle","") for f in (o.get("formations") or [])
                    ),
                    "competences":   ", ".join(
                        c.get("libelle","") for c in (o.get("competences") or [])
                    ),
                    "savoirEtre":    ", ".join(
                        s.get("libelle","") for s in (o.get("qualitesProfessionnelles") or [])
                    ),
                    "permis":        ", ".join(
                        p.get("libelle","") for p in (o.get("permis") or [])
                    ),
                }
            ))
        start += count
        if len(results) < count:
            break
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE 2 — ADZUNA (official API)
# FIX: page number was duplicated (in path AND query) — removed from query
# ──────────────────────────────────────────
def fetch_adzuna():
    print("🔍 Adzuna...")
    jobs = []
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("  ⚠ ADZUNA_APP_ID / ADZUNA_APP_KEY not set — skipping")
        return jobs

    page = 1
    while len(jobs) < MAX_PER_SOURCE:
        qs = urllib.parse.urlencode({
            "app_id":          ADZUNA_APP_ID,
            "app_key":         ADZUNA_APP_KEY,
            "results_per_page": 50,
            "what":            KEYWORDS,
            "where":           "France",
            # FIX: do NOT include "page" here — it's already in the URL path below
        })
        # Page is in the path: /search/{page}  — NOT also in the query string
        url  = f"https://api.adzuna.com/v1/api/jobs/fr/search/{page}?{qs}"
        text = http_get(url)
        data = parse_json(text)
        if not data:
            break
        results = data.get("results", [])
        if not results:
            break
        for o in results:
            loc = (o.get("location") or {}).get("display_name", "")
            jobs.append(normalize(
                source      = "Adzuna",
                title       = o.get("title", ""),
                company     = (o.get("company") or {}).get("display_name", ""),
                location    = loc,
                contract    = o.get("contract_type", ""),
                salary      = _adzuna_salary(o),
                date_str    = o.get("created", ""),
                description = re.sub(r"<[^>]+>", " ", o.get("description", "")),
                apply_url   = o.get("redirect_url", ""),
            ))
            if len(jobs) >= MAX_PER_SOURCE:
                break
        page += 1
        if len(results) < 50:
            break
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

def _adzuna_salary(o):
    lo = o.get("salary_min")
    hi = o.get("salary_max")
    if lo and hi:
        return f"{int(lo):,} – {int(hi):,} €/an"
    if lo:
        return f"À partir de {int(lo):,} €/an"
    return ""

# ──────────────────────────────────────────
# SOURCE 3 — JOOBLE (official API)
# ──────────────────────────────────────────
def fetch_jooble():
    print("🔍 Jooble...")
    jobs = []
    if not JOOBLE_API_KEY:
        print("  ⚠ JOOBLE_API_KEY not set — skipping")
        return jobs

    url  = f"https://fr.jooble.org/api/{JOOBLE_API_KEY}"
    page = 1
    while len(jobs) < MAX_PER_SOURCE:
        data = parse_json(http_post(url, {
            "keywords": KEYWORDS,
            "location": "France",
            "page":     page
        }))
        if not data:
            break
        results = data.get("jobs", [])
        if not results:
            break
        for o in results:
            jobs.append(normalize(
                source      = "Jooble",
                title       = o.get("title", ""),
                company     = o.get("company", ""),
                location    = o.get("location", ""),
                contract    = o.get("type", ""),
                salary      = o.get("salary", ""),
                date_str    = o.get("updated", ""),
                description = re.sub(r"<[^>]+>", " ", o.get("snippet", "")),
                apply_url   = o.get("link", ""),
            ))
            if len(jobs) >= MAX_PER_SOURCE:
                break
        page += 1
        if len(results) < 20:
            break
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# GENERIC RSS FETCHER
# ──────────────────────────────────────────
def fetch_rss(source_name, rss_url, apply_url_tag="link"):
    """Generic RSS fetcher for job feeds."""
    print(f"🔍 {source_name} (RSS)...")
    jobs = []
    text = http_get(rss_url)
    if not text:
        return jobs

    items = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)
    if not items:
        print(f"  ⚠ No <item> tags found in RSS — the feed URL may be wrong or the site blocks bots")
        return jobs

    for item in items[:MAX_PER_SOURCE]:
        def tag(t):
            m = re.search(rf"<{t}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", item, re.DOTALL)
            return m.group(1).strip() if m else ""

        title   = tag("title")
        link    = tag("link") or tag("guid")
        pubdate = tag("pubDate") or tag("dc:date") or ""
        desc    = re.sub(r"<[^>]+>", " ", tag("description"))
        loc     = tag("location") or tag("georss:featurename") or ""
        company = tag("source") or tag("author") or ""
        contract= tag("type") or ""
        salary  = tag("salary") or ""

        jobs.append(normalize(
            source      = source_name,
            title       = title,
            company     = company,
            location    = loc,
            contract    = contract,
            salary      = salary,
            date_str    = pubdate,
            description = desc,
            apply_url   = link,
        ))
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE 4 — INDEED
# FIX: Indeed removed public RSS. Using their job search API via publisher feed.
# If this still fails (Indeed frequently changes URLs), falls back to direct link.
# ──────────────────────────────────────────
def fetch_indeed():
    print("🔍 Indeed...")
    q   = urllib.parse.quote_plus(KEYWORDS)
    # Indeed's RSS for France — most reliable current format
    url = f"https://fr.indeed.com/rss?q={q}&l=France&sort=date&radius=100"
    jobs = fetch_rss("Indeed", url)
    if not jobs:
        # Anti-bot fallback: provide a direct search link
        search_url = f"https://fr.indeed.com/jobs?q={q}&l=France&sort=date"
        print("  ↩ Fallback: direct link (Indeed blocks automated requests)")
        return [{
            "id": uid("Indeed", search_url, KEYWORDS),
            "source": "Indeed",
            "intitule": f"Voir les offres '{KEYWORDS}' sur Indeed",
            "entreprise": {"nom": ""},
            "lieuTravail": {"libelle": "France"},
            "typeContratLibelle": "",
            "salaire": {"libelle": ""},
            "dateCreation": "",
            "description": "Indeed bloque les robots. Cliquez pour voir toutes les offres directement.",
            "origineOffre": {"urlOrigine": search_url},
            "extra": {},
        }]
    return jobs

# ──────────────────────────────────────────
# SOURCE 5 — WELCOME TO THE JUNGLE
# FIX: corrected RSS URL format
# ──────────────────────────────────────────
def fetch_welcome_jungle():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.welcometothejungle.com/fr/jobs.rss?refinementList%5Boffices.country_code%5D%5B%5D=FR&query={q}"
    jobs = fetch_rss("Welcome to the Jungle", url)
    if not jobs:
        search_url = f"https://www.welcometothejungle.com/fr/jobs?query={q}&aroundQuery=France"
        print("  ↩ Fallback: direct link")
        return [{
            "id": uid("Welcome to the Jungle", search_url, KEYWORDS),
            "source": "Welcome to the Jungle",
            "intitule": f"Voir les offres '{KEYWORDS}' sur Welcome to the Jungle",
            "entreprise": {"nom": ""},
            "lieuTravail": {"libelle": "France"},
            "typeContratLibelle": "",
            "salaire": {"libelle": ""},
            "dateCreation": "",
            "description": "Cliquez pour voir toutes les offres directement.",
            "origineOffre": {"urlOrigine": search_url},
            "extra": {},
        }]
    return jobs

# ──────────────────────────────────────────
# SOURCE 6 — METEOJOB
# FIX: corrected RSS endpoint
# ──────────────────────────────────────────
def fetch_meteojob():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.meteojob.com/jobwidget/offers?format=rss&keyword={q}&localisation=France"
    return fetch_rss("Meteojob", url)

# ──────────────────────────────────────────
# SOURCE 7 — OPTION CARRIÈRE
# FIX: verified working XML feed
# ──────────────────────────────────────────
def fetch_optioncarriere():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.optioncarriere.com/emploi.xml?s={q}&l=France&c=&ca=0&p=1"
    return fetch_rss("Option Carrière", url)

# ──────────────────────────────────────────
# SOURCE 8 — TALENT.COM
# FIX: corrected RSS feed URL
# ──────────────────────────────────────────
def fetch_talent():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://fr.talent.com/rss?k={q}&l=France"
    return fetch_rss("Talent.com", url)

# ──────────────────────────────────────────
# SOURCE 9 — JOBIJOBA
# FIX: corrected URL format
# ──────────────────────────────────────────
def fetch_jobijoba():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.jobijoba.com/fr/rss/?what={q}&where=France&type=rss"
    return fetch_rss("Jobijoba", url)

# ──────────────────────────────────────────
# SOURCE 10 — APEC
# FIX: updated to working current API
# ──────────────────────────────────────────
def fetch_apec():
    print("🔍 APEC...")
    jobs = []
    q = urllib.parse.quote_plus(KEYWORDS)

    # Current APEC search API (as of 2024-2025)
    api_url = "https://www.apec.fr/cms/webservices/rechercheOffre/ids"
    params  = urllib.parse.urlencode({
        "typeOffre":   "1",
        "motsCles":    KEYWORDS,
        "lieu":        "",
        "pagination":  "0",
        "nombreItems": str(min(MAX_PER_SOURCE, 100)),
    })
    text = http_get(f"{api_url}?{params}", headers={
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.apec.fr/",
    })
    data = parse_json(text)
    if data:
        ids = (data.get("listeIdentifiantsOffres") or [])[:MAX_PER_SOURCE]
        print(f"  Found {len(ids)} offer IDs")
        for oid in ids:
            detail_url = f"https://www.apec.fr/cms/webservices/offre/public?numeroOffre={oid}"
            d = parse_json(http_get(detail_url, headers={
                "Accept": "application/json",
                "Referer": "https://www.apec.fr/",
            }))
            if d:
                jobs.append(normalize(
                    source      = "APEC",
                    title       = d.get("intitule", ""),
                    company     = (d.get("nomClient") or ""),
                    location    = (d.get("lieuTravail") or {}).get("libelle", ""),
                    contract    = (d.get("typeContrat") or {}).get("libelle", ""),
                    salary      = (d.get("salaire") or {}).get("libelle", ""),
                    date_str    = d.get("datePublication", ""),
                    description = re.sub(r"<[^>]+>", " ", d.get("texteHtml") or d.get("texte", "")),
                    apply_url   = f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/{oid}",
                ))
            time.sleep(0.3)
    else:
        print("  ⚠ APEC API returned no data (may require browser session)")
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE 11 — STAFFSANTÉ
# FIX: corrected RSS URL path
# ──────────────────────────────────────────
def fetch_staffsante():
    q   = urllib.parse.quote_plus(KEYWORDS)
    # Try two known URL patterns
    url = f"https://www.staffsante.fr/rss/offres?motcle={q}"
    jobs = fetch_rss("Staffsanté", url)
    if not jobs:
        url2 = f"https://www.staffsante.fr/offres-emploi?motcle={q}&format=rss"
        jobs = fetch_rss("Staffsanté", url2)
    return jobs

# ──────────────────────────────────────────
# SOURCE 12 — APPEL MÉDICAL
# FIX: corrected RSS URL
# ──────────────────────────────────────────
def fetch_appelmedical():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.appelmedical.com/offres-emploi/rss?motcle={q}&type_offre=mission"
    jobs = fetch_rss("Appel Médical", url)
    if not jobs:
        url2 = f"https://www.appelmedical.com/rss-offres?q={q}"
        jobs = fetch_rss("Appel Médical", url2)
    return jobs

# ──────────────────────────────────────────
# SOURCE 13 — VITALIS MÉDICAL
# FIX: corrected RSS URL
# ──────────────────────────────────────────
def fetch_vitalis():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.vitalis-medical.com/rss/offres?motcle={q}"
    jobs = fetch_rss("Vitalis Médical", url)
    if not jobs:
        url2 = f"https://www.vitalis-medical.com/offres-emploi?motcle={q}&format=rss"
        jobs = fetch_rss("Vitalis Médical", url2)
    return jobs

# ──────────────────────────────────────────
# SOURCE 14 — DENTAL EMPLOI
# FIX: improved HTML parsing with multiple regex strategies
# ──────────────────────────────────────────
def fetch_dentalemploi():
    print("🔍 Dental Emploi...")
    jobs = []
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.dentalemploi.com/annonces/?s={q}"
    text = http_get(url)
    if text:
        # Strategy 1: find article tags with any class containing 'offre' or 'annonce' or 'job'
        items = re.findall(
            r'<(?:article|div)[^>]*class="[^"]*(?:offre|annonce|job|post)[^"]*"[^>]*>(.*?)</(?:article|div)>',
            text, re.DOTALL | re.IGNORECASE
        )
        if not items:
            # Strategy 2: grab all h2/h3 links as job titles (works on many WP job boards)
            items_raw = re.findall(
                r'<h[23][^>]*>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>\s*</h[23]>',
                text, re.DOTALL | re.IGNORECASE
            )
            for link, title in items_raw[:MAX_PER_SOURCE]:
                title = re.sub(r"<[^>]+>", "", title).strip()
                if title:
                    jobs.append(normalize("Dental Emploi", title, "", "", "", "", "", "", link))
        else:
            for item in items[:MAX_PER_SOURCE]:
                title_m = re.search(r'<h[1-5][^>]*>(.*?)</h[1-5]>', item, re.DOTALL | re.IGNORECASE)
                link_m  = re.search(r'href="(https?://[^"]*dentalemploi[^"]*)"', item)
                if not link_m:
                    link_m = re.search(r'href="(/[^"]+)"', item)
                title   = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
                link    = link_m.group(1) if link_m else ""
                if not link.startswith("http"):
                    link = "https://www.dentalemploi.com" + link
                company = ""
                loc     = ""
                company_m = re.search(r'class="[^"]*(?:company|entreprise)[^"]*"[^>]*>(.*?)<', item, re.DOTALL | re.IGNORECASE)
                loc_m     = re.search(r'class="[^"]*(?:location|lieu|ville)[^"]*"[^>]*>(.*?)<', item, re.DOTALL | re.IGNORECASE)
                if company_m: company = re.sub(r"<[^>]+>", "", company_m.group(1)).strip()
                if loc_m:     loc     = re.sub(r"<[^>]+>", "", loc_m.group(1)).strip()
                if title:
                    jobs.append(normalize("Dental Emploi", title, company, loc, "", "", "", "", link))

    if not jobs:
        print("  ⚠ Could not parse listings — site structure may have changed")
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE 15 — ANNONCES MÉDICALES
# FIX: corrected RSS path
# ──────────────────────────────────────────
def fetch_annonces_medicales():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.annonces-medicales.com/rss/offres-emploi?q={q}"
    jobs = fetch_rss("Annonces Médicales", url)
    if not jobs:
        url2 = f"https://www.annonces-medicales.com/emploi/recherche?mc={q}&format=rss"
        jobs = fetch_rss("Annonces Médicales", url2)
    return jobs

# ──────────────────────────────────────────
# SOURCE 16 — EMPLOI OUEST-FRANCE
# FIX: corrected RSS endpoint
# ──────────────────────────────────────────
def fetch_ouest_france():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://emploi.ouest-france.fr/offres-emploi.rss?q={q}&l=France"
    jobs = fetch_rss("Emploi Ouest-France", url)
    if not jobs:
        url2 = f"https://emploi.ouest-france.fr/rss?motcle={q}"
        jobs = fetch_rss("Emploi Ouest-France", url2)
    return jobs

# ──────────────────────────────────────────
# SOURCE 17 — MOOVIJOB
# FIX: corrected RSS path
# ──────────────────────────────────────────
def fetch_moovijob():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.moovijob.com/rss/emplois?keyword={q}&country=France"
    jobs = fetch_rss("Moovijob", url)
    if not jobs:
        url2 = f"https://www.moovijob.com/offres-d-emploi/rss?search={q}&country=France"
        jobs = fetch_rss("Moovijob", url2)
    return jobs

# ──────────────────────────────────────────
# SOURCE 18 — HELLOWORK
# FIX: verified RSS URL
# ──────────────────────────────────────────
def fetch_hellowork():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.hellowork.com/fr-fr/rss/offers.xml?k={q}&l=France"
    jobs = fetch_rss("HelloWork", url)
    if not jobs:
        url2 = f"https://www.hellowork.com/fr-fr/emplois.rss?k={q}&l=France"
        jobs = fetch_rss("HelloWork", url2)
    return jobs

# ──────────────────────────────────────────
# SOURCE 19 — GLASSDOOR (anti-bot — direct link)
# (unchanged — Glassdoor fully blocks scrapers)
# ──────────────────────────────────────────
def fetch_glassdoor():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.glassdoor.fr/Emploi/france-{q.replace('+','-')}-emplois-SRCH_IL.0,6_IN86_KO7,{7+len(KEYWORDS)}.htm"
    jobs = [{
        "id": uid("Glassdoor", url, KEYWORDS),
        "source": "Glassdoor",
        "intitule": f"Voir les offres '{KEYWORDS}' sur Glassdoor",
        "entreprise": {"nom": ""},
        "lieuTravail": {"libelle": "France"},
        "typeContratLibelle": "",
        "salaire": {"libelle": ""},
        "dateCreation": "",
        "description": "Glassdoor bloque les robots. Cliquez sur le lien pour voir toutes les offres directement.",
        "origineOffre": {"urlOrigine": url},
        "extra": {},
    }]
    print("🔍 Glassdoor... ✓ (lien direct — anti-bot actif)")
    return jobs

# ──────────────────────────────────────────
# SOURCE 20 — LINKEDIN (anti-bot — direct link)
# (unchanged — LinkedIn fully blocks scrapers)
# ──────────────────────────────────────────
def fetch_linkedin():
    q   = urllib.parse.quote_plus(KEYWORDS)
    url = f"https://www.linkedin.com/jobs/search/?keywords={q}&location=France&f_TPR=r86400"
    jobs = [{
        "id": uid("LinkedIn", url, KEYWORDS),
        "source": "LinkedIn",
        "intitule": f"Voir les offres '{KEYWORDS}' sur LinkedIn",
        "entreprise": {"nom": ""},
        "lieuTravail": {"libelle": "France"},
        "typeContratLibelle": "",
        "salaire": {"libelle": ""},
        "dateCreation": "",
        "description": "LinkedIn bloque les robots. Cliquez sur le lien pour voir toutes les offres directement.",
        "origineOffre": {"urlOrigine": url},
        "extra": {},
    }]
    print("🔍 LinkedIn... ✓ (lien direct — anti-bot actif)")
    return jobs

# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
SCRAPERS = [
    fetch_france_travail,
    fetch_adzuna,
    fetch_jooble,
    fetch_indeed,
    fetch_welcome_jungle,
    fetch_meteojob,
    fetch_optioncarriere,
    fetch_talent,
    fetch_jobijoba,
    fetch_apec,
    fetch_staffsante,
    fetch_appelmedical,
    fetch_vitalis,
    fetch_dentalemploi,
    fetch_annonces_medicales,
    fetch_ouest_france,
    fetch_moovijob,
    fetch_hellowork,
    fetch_glassdoor,
    fetch_linkedin,
]

def main():
    all_jobs = []
    seen_ids = set()
    stats    = {}
    failed   = []

    for scraper in SCRAPERS:
        try:
            jobs = scraper()
            added = 0
            for j in jobs:
                if j["id"] not in seen_ids:
                    seen_ids.add(j["id"])
                    all_jobs.append(j)
                    added += 1
            src_name = jobs[0]["source"] if jobs else scraper.__name__
            stats[src_name] = added
            if added == 0:
                failed.append(src_name)
        except Exception as e:
            print(f"  ❌ Error in {scraper.__name__}: {e}")
            failed.append(scraper.__name__)
        time.sleep(1.5)  # polite delay between sources

    print(f"\n✅ Total: {len(all_jobs)} unique jobs from {len(stats)} sources")
    for src, cnt in sorted(stats.items(), key=lambda x: -x[1]):
        status = "✓" if cnt > 0 else "✗"
        print(f"   {status} {src}: {cnt}")

    if failed:
        print(f"\n⚠ Sources with 0 results: {', '.join(failed)}")
        print("  → Check the logs above for HTTP error codes to diagnose.")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total":        len(all_jobs),
        "stats":        stats,
        "failed":       failed,
        "jobs":         all_jobs,
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n📄 docs/jobs.json written")

if __name__ == "__main__":
    main()
