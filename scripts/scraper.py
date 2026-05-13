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
KEYWORDS       = "assistant dentaire"
KEYWORDS_URL   = urllib.parse.quote_plus(KEYWORDS)
MAX_PER_SOURCE = 100

# API keys — set as GitHub Secrets
FT_CLIENT_ID     = os.environ.get("FT_CLIENT_ID", "")
FT_CLIENT_SECRET = os.environ.get("FT_CLIENT_SECRET", "")
ADZUNA_APP_ID    = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY   = os.environ.get("ADZUNA_APP_KEY", "")
JSEARCH_API_KEY  = os.environ.get("JSEARCH_API_KEY", "")  # RapidAPI key for JSearch

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP {e.code}: {url[:80]}")
        return ""
    except Exception as e:
        print(f"  ❌ Error: {e} — {url[:80]}")
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
        print(f"  ❌ HTTP {e.code}: {url[:80]}")
        return ""
    except Exception as e:
        print(f"  ❌ Error: {e} — {url[:80]}")
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

def make_link_placeholder(source, search_url):
    """Returns a single direct-link card for sources that block bots."""
    print(f"🔍 {source}... ✓ (lien direct)")
    return [normalize(
        source      = source,
        title       = f"Voir les offres '{KEYWORDS}' sur {source}",
        company     = "",
        location    = "France",
        contract    = "",
        salary      = "",
        date_str    = "",
        description = f"Cliquez sur le lien pour voir toutes les offres '{KEYWORDS}' directement sur {source}.",
        apply_url   = search_url,
    )]

# ──────────────────────────────────────────
# SOURCE 1 — FRANCE TRAVAIL (official API) ✅
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
            jobs.append(normalize(
                source      = "France Travail",
                title       = o.get("intitule", ""),
                company     = (o.get("entreprise") or {}).get("nom", ""),
                location    = (o.get("lieuTravail") or {}).get("libelle", ""),
                contract    = o.get("typeContratLibelle", ""),
                salary      = (o.get("salaire") or {}).get("libelle", ""),
                date_str    = o.get("dateCreation", ""),
                description = o.get("description", ""),
                apply_url   = (o.get("origineOffre") or {}).get("urlOrigine", ""),
                extra       = {
                    "dureeTravail":  o.get("dureeTravailLibelle", ""),
                    "experience":    o.get("experienceLibelle", ""),
                    "qualification": o.get("qualificationLibelle", ""),
                    "secteur":       o.get("secteurActiviteLibelle", ""),
                }
            ))
        start += count
        if len(results) < count:
            break
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE 2 — ADZUNA (official API) ✅
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
            "app_id":           ADZUNA_APP_ID,
            "app_key":          ADZUNA_APP_KEY,
            "results_per_page": 50,
            "what":             KEYWORDS,
            "where":            "France",
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
            lo = o.get("salary_min")
            hi = o.get("salary_max")
            salary = f"{int(lo):,}–{int(hi):,} €/an" if lo and hi else (f"À partir de {int(lo):,} €/an" if lo else "")
            jobs.append(normalize(
                source      = "Adzuna",
                title       = o.get("title", ""),
                company     = (o.get("company") or {}).get("display_name", ""),
                location    = (o.get("location") or {}).get("display_name", ""),
                contract    = o.get("contract_type", ""),
                salary      = salary,
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

# ──────────────────────────────────────────
# SOURCE 3 — JSEARCH via RapidAPI (free tier) ✅
# Covers: Indeed, LinkedIn, Glassdoor, and more in one call
# Free tier: 200 requests/month — enough for daily runs
# Get your free key at: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
# Then add JSEARCH_API_KEY to your GitHub Secrets
# ──────────────────────────────────────────
def fetch_jsearch():
    print("🔍 JSearch (Indeed / LinkedIn / Glassdoor)...")
    jobs = []
    if not JSEARCH_API_KEY:
        print("  ⚠ JSEARCH_API_KEY not set — skipping (add it to GitHub Secrets)")
        return jobs

    page = 1
    while len(jobs) < MAX_PER_SOURCE:
        qs = urllib.parse.urlencode({
            "query":     f"{KEYWORDS} France",
            "page":      str(page),
            "num_pages": "1",
            "country":   "fr",
            "language":  "fr",
        })
        text = http_get(
            f"https://jsearch.p.rapidapi.com/search?{qs}",
            headers={
                "X-RapidAPI-Key":  JSEARCH_API_KEY,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
            }
        )
        data = parse_json(text)
        if not data:
            break
        results = data.get("data", [])
        if not results:
            break
        for o in results:
            lo = o.get("job_min_salary")
            hi = o.get("job_max_salary")
            cur = o.get("job_salary_currency", "€")
            salary = f"{int(lo):,}–{int(hi):,} {cur}" if lo and hi else ""
            jobs.append(normalize(
                source      = o.get("job_publisher", "JSearch"),
                title       = o.get("job_title", ""),
                company     = o.get("employer_name", ""),
                location    = f"{o.get('job_city', '')} {o.get('job_country', '')}".strip(),
                contract    = o.get("job_employment_type", ""),
                salary      = salary,
                date_str    = o.get("job_posted_at_datetime_utc", ""),
                description = o.get("job_description", "")[:500],
                apply_url   = o.get("job_apply_link", ""),
            ))
            if len(jobs) >= MAX_PER_SOURCE:
                break
        page += 1
        if len(results) < 10:
            break
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# ALL OTHER SOURCES — Direct link placeholders
# Points to the "assistant dentaire" search results page on each site
# ──────────────────────────────────────────
def fetch_indeed():
    return make_link_placeholder("Indeed",
        f"https://fr.indeed.com/jobs?q={KEYWORDS_URL}&l=France&sort=date")

def fetch_linkedin():
    return make_link_placeholder("LinkedIn",
        f"https://www.linkedin.com/jobs/search/?keywords={KEYWORDS_URL}&location=France&f_TPR=r86400")

def fetch_glassdoor():
    return make_link_placeholder("Glassdoor",
        f"https://www.glassdoor.fr/Emploi/france-assistant-dentaire-emplois-SRCH_IL.0,6_IN86_KO7,25.htm")

def fetch_jooble():
    return make_link_placeholder("Jooble",
        f"https://fr.jooble.org/emploi-{KEYWORDS.replace(' ', '-')}/France")

def fetch_welcome_jungle():
    return make_link_placeholder("Welcome to the Jungle",
        f"https://www.welcometothejungle.com/fr/jobs?query={KEYWORDS_URL}&aroundQuery=France")

def fetch_hellowork():
    return make_link_placeholder("HelloWork",
        f"https://www.hellowork.com/fr-fr/emplois.html?k={KEYWORDS_URL}&l=France")

def fetch_meteojob():
    return make_link_placeholder("Meteojob",
        f"https://www.meteojob.com/jobsearch/offres?keyword={KEYWORDS_URL}&localisation=France")

def fetch_optioncarriere():
    return make_link_placeholder("Option Carrière",
        f"https://www.optioncarriere.com/emploi.html?s={KEYWORDS_URL}&l=France")

def fetch_talent():
    return make_link_placeholder("Talent.com",
        f"https://fr.talent.com/jobs?k={KEYWORDS_URL}&l=France")

def fetch_jobijoba():
    return make_link_placeholder("Jobijoba",
        f"https://www.jobijoba.com/fr/offres-emploi/?what={KEYWORDS_URL}&where=France")

def fetch_moovijob():
    return make_link_placeholder("Moovijob",
        f"https://www.moovijob.com/offres-d-emploi?keyword={KEYWORDS_URL}&country=France")

def fetch_apec():
    return make_link_placeholder("APEC",
        f"https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={KEYWORDS_URL}")

def fetch_staffsante():
    return make_link_placeholder("Staffsanté",
        f"https://www.staffsante.fr/offres-emploi?motcle={KEYWORDS_URL}")

def fetch_appelmedical():
    return make_link_placeholder("Appel Médical",
        f"https://www.appelmedical.com/offres-d-emploi?motcle={KEYWORDS_URL}")

def fetch_vitalis():
    return make_link_placeholder("Vitalis Médical",
        f"https://www.vitalis-medical.com/offres-d-emploi?motcle={KEYWORDS_URL}")

def fetch_dentalemploi():
    return make_link_placeholder("Dental Emploi",
        f"https://www.dentalemploi.com/annonces/?s={KEYWORDS_URL}")

def fetch_annonces_medicales():
    return make_link_placeholder("Annonces Médicales",
        f"https://www.annonces-medicales.com/emploi/recherche?mc={KEYWORDS_URL}")

def fetch_ouest_france():
    return make_link_placeholder("Emploi Ouest-France",
        f"https://emploi.ouest-france.fr/offres-emploi?q={KEYWORDS_URL}&l=France")

# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
SCRAPERS = [
    fetch_france_travail,
    fetch_adzuna,
    fetch_jsearch,
    fetch_indeed,
    fetch_linkedin,
    fetch_glassdoor,
    fetch_jooble,
    fetch_welcome_jungle,
    fetch_hellowork,
    fetch_meteojob,
    fetch_optioncarriere,
    fetch_talent,
    fetch_jobijoba,
    fetch_moovijob,
    fetch_apec,
    fetch_staffsante,
    fetch_appelmedical,
    fetch_vitalis,
    fetch_dentalemploi,
    fetch_annonces_medicales,
    fetch_ouest_france,
]

def main():
    all_jobs = []
    seen_ids = set()
    stats    = {}

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
        except Exception as e:
            print(f"  ❌ Error in {scraper.__name__}: {e}")
        time.sleep(1)

    print(f"\n✅ Total: {len(all_jobs)} entries from {len(stats)} sources")
    for src, cnt in stats.items():
        print(f"   {'✓' if cnt > 0 else '✗'} {src}: {cnt}")

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
