"""
Dental Job Scraper — Assistant Dentaire
Searches all configured sources and outputs jobs.json
"""

import os, json, time, hashlib, re
from datetime import datetime, timezone
import urllib.request, urllib.parse, urllib.error

# ──────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────
KEYWORDS   = "assistant dentaire"
LOCATION   = ""          # empty = whole France
MAX_PER_SOURCE = 100

# API keys — set as GitHub Secrets (see README)
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

def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {
        "User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)"
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  GET error {url[:80]}: {e}")
        return ""

def http_post(url, data, headers=None, timeout=15):
    body = json.dumps(data).encode()
    h = {"Content-Type": "application/json", "User-Agent": "JobBot/1.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  POST error {url[:80]}: {e}")
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

    # 1. Get token
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
        print(f"  Token error: {e}")
        return jobs

    # 2. Search offers (paginated, max 150 per call)
    base = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
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
            "app_id":   ADZUNA_APP_ID,
            "app_key":  ADZUNA_APP_KEY,
            "results_per_page": 50,
            "what":     KEYWORDS,
            "where":    "France",
            "page":     page,
            "content-type": "application/json"
        })
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
# SOURCE 4 — INDEED (RSS)
# ──────────────────────────────────────────
def fetch_rss(source_name, rss_url, apply_url_tag="link"):
    """Generic RSS fetcher for job feeds."""
    print(f"🔍 {source_name} (RSS)...")
    jobs = []
    text = http_get(rss_url)
    if not text:
        return jobs

    items = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)
    for item in items[:MAX_PER_SOURCE]:
        def tag(t):
            m = re.search(rf"<{t}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", item, re.DOTALL)
            return m.group(1).strip() if m else ""

        title   = tag("title")
        link    = tag("link") or tag("guid")
        pubdate = tag("pubDate") or tag("dc:date") or ""
        desc    = re.sub(r"<[^>]+>", " ", tag("description"))
        loc     = tag("location") or ""
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

def fetch_indeed():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://fr.indeed.com/rss?q={q}&l=France&sort=date"
    return fetch_rss("Indeed", url)

def fetch_welcome_jungle():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.welcometothejungle.com/fr/jobs.rss?query={q}&aroundRadius=&page=1"
    return fetch_rss("Welcome to the Jungle", url)

def fetch_meteojob():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.meteojob.com/jobwidget/offers?format=rss&keyword={q}&localisation=France"
    return fetch_rss("Meteojob", url)

def fetch_optioncarriere():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.optioncarriere.com/emploi.xml?s={q}&l=France"
    return fetch_rss("Option Carrière", url)

def fetch_talent():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://fr.talent.com/rss?k={q}&l=France"
    return fetch_rss("Talent.com", url)

def fetch_jobijoba():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.jobijoba.com/fr/rss/?what={q}&where=France"
    return fetch_rss("Jobijoba", url)

# ──────────────────────────────────────────
# SOURCE — APEC (scrape-friendly search)
# ──────────────────────────────────────────
def fetch_apec():
    print("🔍 APEC...")
    jobs = []
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://cadres.apec.fr/offres-emploi-cadres/resultat-recherche-offres-emploi.html?typeOffre=1&motsCles={q}&lieu=France"
    # APEC has a JSON API endpoint
    api = f"https://cadres.apec.fr/cms/webservices/rechercheOffre/ids?typeOffre=1&motsCles={q}&lieu=France&pagination=0&nombreItems=100"
    text = http_get(api, headers={"Accept": "application/json"})
    data = parse_json(text)
    if data:
        ids = (data.get("listeIdentifiantsOffres") or [])[:MAX_PER_SOURCE]
        for oid in ids:
            detail_url = f"https://cadres.apec.fr/cms/webservices/offre/public?numeroOffre={oid}"
            d = parse_json(http_get(detail_url, headers={"Accept": "application/json"}))
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
                    apply_url   = f"https://cadres.apec.fr/offres-emploi-cadres/{oid}.html",
                ))
            time.sleep(0.2)
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE — STAFFSANTE (medical jobs)
# ──────────────────────────────────────────
def fetch_staffsante():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.staffsante.fr/offres-emploi/rss?search={q}"
    return fetch_rss("Staffsanté", url)

# ──────────────────────────────────────────
# SOURCE — APPELMEDICAL
# ──────────────────────────────────────────
def fetch_appelmedical():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.appelmedical.com/offres-d-emploi/rss?search={q}"
    return fetch_rss("Appel Médical", url)

# ──────────────────────────────────────────
# SOURCE — VITALIS MEDICAL
# ──────────────────────────────────────────
def fetch_vitalis():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.vitalis-medical.com/offres-d-emploi/rss?search={q}"
    return fetch_rss("Vitalis Médical", url)

# ──────────────────────────────────────────
# SOURCE — DENTAL EMPLOI
# ──────────────────────────────────────────
def fetch_dentalemploi():
    print("🔍 Dental Emploi...")
    jobs = []
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.dentalemploi.com/annonces/?search={q}"
    text = http_get(url)
    if text:
        # Parse job listings from HTML
        items = re.findall(r'<article[^>]*class="[^"]*job[^"]*"[^>]*>(.*?)</article>', text, re.DOTALL | re.IGNORECASE)
        for item in items[:MAX_PER_SOURCE]:
            def tag_re(pattern):
                m = re.search(pattern, item, re.DOTALL | re.IGNORECASE)
                return m.group(1).strip() if m else ""
            title   = re.sub(r"<[^>]+>", "", tag_re(r'<h\d[^>]*>(.*?)</h\d>'))
            link_m  = re.search(r'href="(https?://[^"]*dentalemploi[^"]*)"', item)
            link    = link_m.group(1) if link_m else ""
            company = re.sub(r"<[^>]+>", "", tag_re(r'class="[^"]*company[^"]*"[^>]*>(.*?)<'))
            loc     = re.sub(r"<[^>]+>", "", tag_re(r'class="[^"]*location[^"]*"[^>]*>(.*?)<'))
            if title:
                jobs.append(normalize("Dental Emploi", title, company, loc, "", "", "", "", link))
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE — ANNONCES MEDICALES
# ──────────────────────────────────────────
def fetch_annonces_medicales():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.annonces-medicales.com/emploi/rss?search={q}"
    return fetch_rss("Annonces Médicales", url)

# ──────────────────────────────────────────
# SOURCE — EMPLOI OUEST FRANCE
# ──────────────────────────────────────────
def fetch_ouest_france():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://emploi.ouest-france.fr/offres-emploi/rss?q={q}"
    return fetch_rss("Emploi Ouest-France", url)

# ──────────────────────────────────────────
# SOURCE — MOOVIJOB
# ──────────────────────────────────────────
def fetch_moovijob():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.moovijob.com/offres-d-emploi/rss?search={q}"
    return fetch_rss("Moovijob", url)

# ──────────────────────────────────────────
# SOURCE — HELLOWORK
# ──────────────────────────────────────────
def fetch_hellowork():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.hellowork.com/fr-fr/rss/offers.xml?k={q}&l=France"
    return fetch_rss("HelloWork", url)

# ──────────────────────────────────────────
# SOURCE — GLASSDOOR (RSS fallback)
# ──────────────────────────────────────────
def fetch_glassdoor():
    q = urllib.parse.quote(KEYWORDS)
    url = f"https://www.glassdoor.fr/Job/emplois.htm?suggestCount=0&suggestChosen=false&clickSource=searchBtn&typedKeyword={q}&sc.keyword={q}&locT=N&locId=3&jobType="
    # Glassdoor blocks bots — we return a placeholder pointing to their search
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
    print(f"🔍 Glassdoor... ✓ (lien direct — anti-bot actif)")
    return jobs

# ──────────────────────────────────────────
# SOURCE — LINKEDIN (RSS fallback)
# ──────────────────────────────────────────
def fetch_linkedin():
    q   = urllib.parse.quote(KEYWORDS)
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
    print(f"🔍 LinkedIn... ✓ (lien direct — anti-bot actif)")
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
    stats = {}

    for scraper in SCRAPERS:
        try:
            jobs = scraper()
            added = 0
            for j in jobs:
                if j["id"] not in seen_ids:
                    seen_ids.add(j["id"])
                    all_jobs.append(j)
                    added += 1
            stats[jobs[0]["source"] if jobs else scraper.__name__] = added
        except Exception as e:
            print(f"  ❌ Error in {scraper.__name__}: {e}")
        time.sleep(1)  # polite delay between sources

    print(f"\n✅ Total: {len(all_jobs)} unique jobs from {len(stats)} sources")
    for src, cnt in stats.items():
        print(f"   {src}: {cnt}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total":        len(all_jobs),
        "stats":        stats,
        "jobs":         all_jobs,
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("\n📄 docs/jobs.json written")

if __name__ == "__main__":
    main()
