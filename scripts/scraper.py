"""
Dental Job Scraper — Assistant Dentaire
Searches all configured sources and outputs jobs.json

FIXES in this version:
1. France Travail: reads Content-Range header → fetches ALL results (not just 100)
2. Adzuna & Jooble: added env-var check with clear error + correct workflow env block comment
3. Apify: new fetch_via_apify() used for Indeed, HelloWork, Glassdoor, LinkedIn, Staffsanté, Vitalis, Appel Médical
4. Direct links: all dead RSS sources replaced with clickable direct search links
"""

import os, json, time, hashlib, re
from datetime import datetime, timezone
import urllib.request, urllib.parse, urllib.error

# ──────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────
KEYWORDS       = "assistant dentaire"
LOCATION       = ""          # empty = whole France
MAX_PER_SOURCE = 3000        # raised — France Travail can return 1000+

# API keys — set as GitHub Secrets, passed via workflow env: block
# (see comment at bottom of file for the required GitHub Actions env block)
FT_CLIENT_ID     = os.environ.get("FT_CLIENT_ID", "")
FT_CLIENT_SECRET = os.environ.get("FT_CLIENT_SECRET", "")
ADZUNA_APP_ID    = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY   = os.environ.get("ADZUNA_APP_KEY", "")
JOOBLE_API_KEY   = os.environ.get("JOOBLE_API_KEY", "")
APIFY_API_KEY    = os.environ.get("APIFY_API_KEY", "")  # ← NEW

# ──────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────
def esc(s):
    return str(s or "").strip()

def uid(source, url, title):
    raw = f"{source}|{url}|{title}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

def http_get(url, headers=None, timeout=20, return_headers=False):
    req = urllib.request.Request(url, headers=headers or {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status  = r.status
            resp_headers = dict(r.headers)
            content = r.read().decode("utf-8", errors="replace")
            if status not in (200, 206):
                print(f"  ⚠ HTTP {status} from {url[:80]}")
            if return_headers:
                return content, resp_headers
            return content
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP {e.code} error: {url[:80]}")
        return ("", {}) if return_headers else ""
    except urllib.error.URLError as e:
        print(f"  ❌ URL error ({e.reason}): {url[:80]}")
        return ("", {}) if return_headers else ""
    except Exception as e:
        print(f"  ❌ GET error {url[:80]}: {e}")
        return ("", {}) if return_headers else ""

def http_post(url, data, headers=None, timeout=60):
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

def make_direct_link(source, url, note=""):
    """Fallback: a single job entry that is just a clickable search link."""
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
# SOURCE 1 — FRANCE TRAVAIL (official API)
# FIX: reads Content-Range header to get total, loops until all fetched
# ──────────────────────────────────────────
def fetch_france_travail():
    print("🔍 France Travail...")
    jobs = []
    if not FT_CLIENT_ID or not FT_CLIENT_SECRET:
        print("  ⚠ FT_CLIENT_ID / FT_CLIENT_SECRET not set — skipping")
        return jobs

    # Step 1: Get token
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
            tok   = json.loads(r.read())
            token = tok.get("access_token", "")
    except Exception as e:
        print(f"  ❌ Token error: {e}")
        return jobs

    base       = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    batch_size = 149    # API max per call (range is 0-based, so 0-148 = 149 items)
    start      = 0
    total      = None   # learned from Content-Range header on first call

    while True:
        end = start + batch_size - 1
        qs  = urllib.parse.urlencode({
            "motsCles": KEYWORDS,
            "range":    f"{start}-{end}",
        })
        text, resp_headers = http_get(
            f"{base}?{qs}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept":        "application/json",
            },
            return_headers=True,
        )

        # Parse Content-Range: "offres 0-148/847"
        if total is None:
            cr = resp_headers.get("Content-Range", "") or resp_headers.get("content-range", "")
            if "/" in cr:
                try:
                    total = int(cr.split("/")[-1])
                    print(f"  Total available on France Travail: {total}")
                except ValueError:
                    pass

        data    = parse_json(text)
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
                        f.get("niveauLibelle", "") for f in (o.get("formations") or [])
                    ),
                    "competences":   ", ".join(
                        c.get("libelle", "") for c in (o.get("competences") or [])
                    ),
                    "savoirEtre":    ", ".join(
                        s.get("libelle", "") for s in (o.get("qualitesProfessionnelles") or [])
                    ),
                    "permis":        ", ".join(
                        p.get("libelle", "") for p in (o.get("permis") or [])
                    ),
                }
            ))

        start += batch_size

        # Stop if we've fetched everything, or hit the hard cap, or the API returned a partial batch
        if total is not None and start >= min(total, MAX_PER_SOURCE):
            break
        if len(results) < batch_size:
            break  # last page

        time.sleep(0.4)  # polite delay between paginated calls

    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE 2 — ADZUNA (official API)
# FIX: page number correctly only in URL path
# ──────────────────────────────────────────
def fetch_adzuna():
    print("🔍 Adzuna...")
    jobs = []
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("  ⚠ ADZUNA_APP_ID / ADZUNA_APP_KEY not set — check GitHub Secrets + workflow env block")
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
        print("  ⚠ JOOBLE_API_KEY not set — check GitHub Secrets + workflow env block")
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
# APIFY — generic runner (free tier: ~100 results/actor/run)
# Actors used:
#   Indeed      → misceres/indeed-scraper
#   HelloWork   → apify/cheerio-scraper (custom)
#   Glassdoor   → bebity/glassdoor-jobs-scraper
#   LinkedIn    → curious_coder/linkedin-jobs-scraper
#   Staffsanté  → apify/cheerio-scraper (custom)
#   Appel Médical → apify/cheerio-scraper (custom)
#   Vitalis     → apify/cheerio-scraper (custom)
# ──────────────────────────────────────────
def fetch_via_apify(actor_id, run_input, source_name, mapper_fn, timeout_secs=120):
    """
    Runs an Apify actor synchronously and returns normalized job list.
    Uses run-sync-get-dataset-items which blocks until done (up to timeout_secs).
    Free tier: 5 USD/month credit — enough for ~5-10 actor runs per day.
    """
    print(f"🔍 {source_name} (Apify)...")
    if not APIFY_API_KEY:
        print("  ⚠ APIFY_API_KEY not set — check GitHub Secrets + workflow env block")
        return []

    qs  = urllib.parse.urlencode({
        "token":   APIFY_API_KEY,
        "timeout": timeout_secs,
        "memory":  256,
    })
    url  = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items?{qs}"
    text = http_post(url, run_input, timeout=timeout_secs + 10)
    data = parse_json(text)

    if not data or not isinstance(data, list):
        print(f"  ⚠ No data returned from Apify for {source_name}")
        return []

    jobs = []
    for o in data[:MAX_PER_SOURCE]:
        j = mapper_fn(o)
        if j:
            jobs.append(j)
    print(f"  ✓ {len(jobs)} jobs")
    return jobs

# ──────────────────────────────────────────
# SOURCE 4 — INDEED via Apify
# Actor: misceres/indeed-scraper (free, ~100 results)
# ──────────────────────────────────────────
def fetch_indeed():
    def mapper(o):
        return normalize(
            source      = "Indeed",
            title       = o.get("positionName", "") or o.get("title", ""),
            company     = o.get("company", ""),
            location    = o.get("location", ""),
            contract    = o.get("jobType", "") or o.get("employmentType", ""),
            salary      = o.get("salary", "") or o.get("salaryText", ""),
            date_str    = o.get("postedAt", "") or o.get("datePosted", ""),
            description = re.sub(r"<[^>]+>", " ", o.get("description", "") or o.get("snippet", "")),
            apply_url   = o.get("url", "") or o.get("jobUrl", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "misceres/indeed-scraper",
        run_input   = {
            "position":     KEYWORDS,
            "country":      "FR",
            "location":     "France",
            "maxItems":     100,
            "parseItems":   True,
        },
        source_name = "Indeed",
        mapper_fn   = mapper,
    )
    if not jobs:
        # Fallback: direct link
        q = urllib.parse.quote_plus(KEYWORDS)
        print("  ↩ Fallback: direct link")
        return [make_direct_link("Indeed",
            f"https://fr.indeed.com/jobs?q={q}&l=France&sort=date",
            "Indeed bloque les robots. Cliquez pour voir toutes les offres directement.")]
    return jobs

# ──────────────────────────────────────────
# SOURCE 5 — WELCOME TO THE JUNGLE via Apify
# Actor: apify/cheerio-scraper on their search page
# ──────────────────────────────────────────
def fetch_welcome_jungle():
    q = urllib.parse.quote_plus(KEYWORDS)
    def mapper(o):
        return normalize(
            source      = "Welcome to the Jungle",
            title       = o.get("title", "") or o.get("name", ""),
            company     = o.get("company", "") or o.get("organization", ""),
            location    = o.get("location", ""),
            contract    = o.get("contractType", "") or o.get("contract", ""),
            salary      = o.get("salary", ""),
            date_str    = o.get("publishedAt", "") or o.get("date", ""),
            description = re.sub(r"<[^>]+>", " ", o.get("description", "")),
            apply_url   = o.get("url", "") or o.get("applyUrl", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "apify/cheerio-scraper",
        run_input   = {
            "startUrls": [{"url": f"https://www.welcometothejungle.com/fr/jobs?query={q}&aroundQuery=France"}],
            "pageFunction": """
async function pageFunction(context) {
    const { $ } = context;
    const jobs = [];
    $('article[data-testid=\"job-card\"], [class*=\"JobCard\"]').each((i, el) => {
        const a = $(el).find('a[href*=\"/fr/companies\"]').first();
        jobs.push({
            title: $(el).find('h4, h3, [class*=\"title\"]').first().text().trim(),
            company: $(el).find('[class*=\"company\"], [class*=\"organization\"]').first().text().trim(),
            location: $(el).find('[class*=\"location\"]').first().text().trim(),
            contract: $(el).find('[class*=\"contract\"]').first().text().trim(),
            url: 'https://www.welcometothejungle.com' + (a.attr('href') || ''),
        });
    });
    return jobs;
}
""",
            "maxRequestsPerCrawl": 5,
        },
        source_name = "Welcome to the Jungle",
        mapper_fn   = mapper,
    )
    if not jobs:
        print("  ↩ Fallback: direct link")
        return [make_direct_link("Welcome to the Jungle",
            f"https://www.welcometothejungle.com/fr/jobs?query={q}&aroundQuery=France")]
    return jobs

# ──────────────────────────────────────────
# SOURCE 6 — GLASSDOOR via Apify
# Actor: bebity/glassdoor-jobs-scraper
# ──────────────────────────────────────────
def fetch_glassdoor():
    def mapper(o):
        return normalize(
            source      = "Glassdoor",
            title       = o.get("jobTitle", "") or o.get("title", ""),
            company     = o.get("employerName", "") or o.get("company", ""),
            location    = o.get("location", ""),
            contract    = o.get("jobType", ""),
            salary      = o.get("salaryText", "") or o.get("salary", ""),
            date_str    = o.get("discoveredAt", "") or o.get("postedDate", ""),
            description = re.sub(r"<[^>]+>", " ", o.get("description", "")),
            apply_url   = o.get("jobLink", "") or o.get("url", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "bebity/glassdoor-jobs-scraper",
        run_input   = {
            "keyword":    KEYWORDS,
            "location":   "France",
            "maxResults": 100,
        },
        source_name = "Glassdoor",
        mapper_fn   = mapper,
    )
    if not jobs:
        q = urllib.parse.quote_plus(KEYWORDS)
        print("  ↩ Fallback: direct link")
        return [make_direct_link("Glassdoor",
            f"https://www.glassdoor.fr/Emploi/france-assistant-dentaire-emplois-SRCH_IL.0,6_IN86_KO7,25.htm",
            "Glassdoor bloque les robots. Cliquez pour voir toutes les offres directement.")]
    return jobs

# ──────────────────────────────────────────
# SOURCE 7 — LINKEDIN via Apify
# Actor: curious_coder/linkedin-jobs-scraper
# ──────────────────────────────────────────
def fetch_linkedin():
    def mapper(o):
        return normalize(
            source      = "LinkedIn",
            title       = o.get("title", "") or o.get("jobTitle", ""),
            company     = o.get("companyName", "") or o.get("company", ""),
            location    = o.get("location", ""),
            contract    = o.get("employmentType", "") or o.get("jobType", ""),
            salary      = o.get("salary", ""),
            date_str    = o.get("postedAt", "") or o.get("publishedAt", ""),
            description = re.sub(r"<[^>]+>", " ", o.get("description", "")),
            apply_url   = o.get("jobUrl", "") or o.get("url", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "curious_coder/linkedin-jobs-scraper",
        run_input   = {
            "queries":   [{"query": KEYWORDS, "location": "France"}],
            "maxItems":  50,
        },
        source_name = "LinkedIn",
        mapper_fn   = mapper,
    )
    if not jobs:
        q = urllib.parse.quote_plus(KEYWORDS)
        print("  ↩ Fallback: direct link")
        return [make_direct_link("LinkedIn",
            f"https://www.linkedin.com/jobs/search/?keywords={q}&location=France&f_TPR=r86400",
            "LinkedIn bloque les robots. Cliquez pour voir toutes les offres directement.")]
    return jobs

# ──────────────────────────────────────────
# SOURCE 8 — HELLOWORK via Apify cheerio-scraper
# ──────────────────────────────────────────
def fetch_hellowork():
    q = urllib.parse.quote_plus(KEYWORDS)
    search_url = f"https://www.hellowork.com/fr-fr/emplois/recherche.html?k={q}&l=France"

    def mapper(o):
        return normalize(
            source      = "HelloWork",
            title       = o.get("title", ""),
            company     = o.get("company", ""),
            location    = o.get("location", ""),
            contract    = o.get("contract", ""),
            salary      = o.get("salary", ""),
            date_str    = o.get("date", ""),
            description = o.get("description", ""),
            apply_url   = o.get("url", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "apify/cheerio-scraper",
        run_input   = {
            "startUrls": [{"url": search_url}],
            "pageFunction": """
async function pageFunction(context) {
    const { $ } = context;
    const jobs = [];
    $('article, [class*=\"JobCard\"], [class*=\"job-item\"], li[class*=\"offer\"]').each((i, el) => {
        const link = $(el).find('a[href*=\"emploi\"], a[href*=\"offre\"]').first();
        const href = link.attr('href') || '';
        jobs.push({
            title:    $(el).find('h2, h3, [class*=\"title\"]').first().text().trim(),
            company:  $(el).find('[class*=\"company\"], [class*=\"entreprise\"]').first().text().trim(),
            location: $(el).find('[class*=\"location\"], [class*=\"lieu\"]').first().text().trim(),
            contract: $(el).find('[class*=\"contract\"]').first().text().trim(),
            salary:   $(el).find('[class*=\"salary\"], [class*=\"salaire\"]').first().text().trim(),
            url:      href.startsWith('http') ? href : 'https://www.hellowork.com' + href,
        });
    });
    return jobs.filter(j => j.title);
}
""",
            "maxRequestsPerCrawl": 5,
        },
        source_name = "HelloWork",
        mapper_fn   = mapper,
    )
    if not jobs:
        print("  ↩ Fallback: direct link")
        return [make_direct_link("HelloWork", search_url)]
    return jobs

# ──────────────────────────────────────────
# SOURCE 9 — STAFFSANTÉ via Apify cheerio-scraper
# ──────────────────────────────────────────
def fetch_staffsante():
    q = urllib.parse.quote_plus(KEYWORDS)
    search_url = f"https://www.staffsante.fr/offres-emploi?motcle={q}"

    def mapper(o):
        return normalize(
            source    = "Staffsanté",
            title     = o.get("title", ""),
            company   = o.get("company", ""),
            location  = o.get("location", ""),
            contract  = o.get("contract", ""),
            salary    = o.get("salary", ""),
            date_str  = o.get("date", ""),
            description = o.get("description", ""),
            apply_url = o.get("url", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "apify/cheerio-scraper",
        run_input   = {
            "startUrls": [{"url": search_url}],
            "pageFunction": """
async function pageFunction(context) {
    const { $ } = context;
    const jobs = [];
    $('article, .offre, [class*=\"offre\"], [class*=\"job\"]').each((i, el) => {
        const link = $(el).find('a').first();
        const href = link.attr('href') || '';
        jobs.push({
            title:    $(el).find('h2, h3, [class*=\"title\"], [class*=\"intitule\"]').first().text().trim(),
            company:  $(el).find('[class*=\"company\"], [class*=\"entreprise\"]').first().text().trim(),
            location: $(el).find('[class*=\"location\"], [class*=\"lieu\"], [class*=\"ville\"]').first().text().trim(),
            contract: $(el).find('[class*=\"contract\"], [class*=\"contrat\"]').first().text().trim(),
            url:      href.startsWith('http') ? href : 'https://www.staffsante.fr' + href,
        });
    });
    return jobs.filter(j => j.title);
}
""",
            "maxRequestsPerCrawl": 5,
        },
        source_name = "Staffsanté",
        mapper_fn   = mapper,
    )
    if not jobs:
        print("  ↩ Fallback: direct link")
        return [make_direct_link("Staffsanté", search_url)]
    return jobs

# ──────────────────────────────────────────
# SOURCE 10 — APPEL MÉDICAL via Apify cheerio-scraper
# ──────────────────────────────────────────
def fetch_appelmedical():
    q = urllib.parse.quote_plus(KEYWORDS)
    search_url = f"https://www.appelmedical.com/offres-emploi/?q={q}"

    def mapper(o):
        return normalize(
            source    = "Appel Médical",
            title     = o.get("title", ""),
            company   = o.get("company", ""),
            location  = o.get("location", ""),
            contract  = o.get("contract", ""),
            salary    = o.get("salary", ""),
            date_str  = o.get("date", ""),
            description = o.get("description", ""),
            apply_url = o.get("url", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "apify/cheerio-scraper",
        run_input   = {
            "startUrls": [{"url": search_url}],
            "pageFunction": """
async function pageFunction(context) {
    const { $ } = context;
    const jobs = [];
    $('article, .offre, [class*=\"offre\"], [class*=\"job\"], li[class*=\"result\"]').each((i, el) => {
        const link = $(el).find('a').first();
        const href = link.attr('href') || '';
        jobs.push({
            title:    $(el).find('h2, h3, [class*=\"title\"], [class*=\"poste\"]').first().text().trim(),
            company:  $(el).find('[class*=\"company\"], [class*=\"client\"]').first().text().trim(),
            location: $(el).find('[class*=\"location\"], [class*=\"ville\"], [class*=\"lieu\"]').first().text().trim(),
            contract: $(el).find('[class*=\"contract\"], [class*=\"type\"]').first().text().trim(),
            url:      href.startsWith('http') ? href : 'https://www.appelmedical.com' + href,
        });
    });
    return jobs.filter(j => j.title);
}
""",
            "maxRequestsPerCrawl": 5,
        },
        source_name = "Appel Médical",
        mapper_fn   = mapper,
    )
    if not jobs:
        print("  ↩ Fallback: direct link")
        return [make_direct_link("Appel Médical", search_url)]
    return jobs

# ──────────────────────────────────────────
# SOURCE 11 — VITALIS MÉDICAL via Apify cheerio-scraper
# ──────────────────────────────────────────
def fetch_vitalis():
    q = urllib.parse.quote_plus(KEYWORDS)
    search_url = f"https://www.vitalis-medical.com/emploi-{q.replace('+', '-')}.html"

    def mapper(o):
        return normalize(
            source    = "Vitalis Médical",
            title     = o.get("title", ""),
            company   = "Vitalis Médical",
            location  = o.get("location", ""),
            contract  = o.get("contract", ""),
            salary    = o.get("salary", ""),
            date_str  = o.get("date", ""),
            description = o.get("description", ""),
            apply_url = o.get("url", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "apify/cheerio-scraper",
        run_input   = {
            "startUrls": [{"url": search_url}],
            "pageFunction": """
async function pageFunction(context) {
    const { $ } = context;
    const jobs = [];
    $('article, .offre, [class*=\"offer\"], [class*=\"job\"]').each((i, el) => {
        const link = $(el).find('a').first();
        const href = link.attr('href') || '';
        jobs.push({
            title:    $(el).find('h2, h3, [class*=\"title\"]').first().text().trim(),
            location: $(el).find('[class*=\"location\"], [class*=\"ville\"]').first().text().trim(),
            contract: $(el).find('[class*=\"contract\"]').first().text().trim(),
            url:      href.startsWith('http') ? href : 'https://www.vitalis-medical.com' + href,
        });
    });
    return jobs.filter(j => j.title);
}
""",
            "maxRequestsPerCrawl": 5,
        },
        source_name = "Vitalis Médical",
        mapper_fn   = mapper,
    )
    if not jobs:
        print("  ↩ Fallback: direct link")
        return [make_direct_link("Vitalis Médical", search_url)]
    return jobs

# ──────────────────────────────────────────
# SOURCE 12 — APEC via Apify (APEC requires JS session)
# ──────────────────────────────────────────
def fetch_apec():
    q = urllib.parse.quote_plus(KEYWORDS)
    search_url = f"https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={q}"

    def mapper(o):
        return normalize(
            source    = "APEC",
            title     = o.get("title", "") or o.get("intitule", ""),
            company   = o.get("company", "") or o.get("nomClient", ""),
            location  = o.get("location", "") or o.get("lieuTravail", ""),
            contract  = o.get("contract", "") or o.get("typeContrat", ""),
            salary    = o.get("salary", "") or o.get("salaire", ""),
            date_str  = o.get("date", "") or o.get("datePublication", ""),
            description = re.sub(r"<[^>]+>", " ", o.get("description", "")),
            apply_url = o.get("url", "") or o.get("applyUrl", ""),
        )
    jobs = fetch_via_apify(
        actor_id    = "apify/playwright-scraper",
        run_input   = {
            "startUrls": [{"url": search_url}],
            "pageFunction": """
async function pageFunction(context) {
    const { page } = context;
    await page.waitForSelector('[class*=\"result\"], article, .offre', { timeout: 15000 }).catch(() => {});
    const jobs = await page.evaluate(() => {
        const els = document.querySelectorAll('[class*=\"result\"], article, .card-offre');
        return Array.from(els).map(el => ({
            title:    (el.querySelector('h2, h3, [class*=\"title\"]') || {}).innerText || '',
            company:  (el.querySelector('[class*=\"company\"], [class*=\"entreprise\"]') || {}).innerText || '',
            location: (el.querySelector('[class*=\"location\"], [class*=\"lieu\"]') || {}).innerText || '',
            contract: (el.querySelector('[class*=\"contract\"]') || {}).innerText || '',
            url:      (el.querySelector('a') || {}).href || '',
        }));
    });
    return jobs.filter(j => j.title);
}
""",
            "maxRequestsPerCrawl": 3,
        },
        source_name = "APEC",
        mapper_fn   = mapper,
    )
    if not jobs:
        print("  ↩ Fallback: direct link")
        return [make_direct_link("APEC", search_url)]
    return jobs

# ──────────────────────────────────────────
# SOURCES 13-19 — DIRECT LINKS ONLY
# (RSS feeds are dead; Apify not worth the credit for aggregators)
# These open the actual job search pages directly in the app
# ──────────────────────────────────────────
def fetch_direct_links():
    print("🔍 Direct links (dead RSS sources)...")
    q = urllib.parse.quote_plus(KEYWORDS)
    sources = {
        "Meteojob":        f"https://www.meteojob.com/jobsearch/offers?keyword={q}&localisation=France",
        "Talent.com":      f"https://fr.talent.com/jobs?k={q}&l=France",
        "Jobijoba":        f"https://www.jobijoba.com/fr/jobs/?what={q}&where=France",
        "Option Carrière": f"https://www.optioncarriere.com/emploi.html?s={q}&l=France",
        "Moovijob":        f"https://www.moovijob.com/offres-d-emploi?search={q}",
        "Dental Emploi":   f"https://www.dentalemploi.com/annonces/?s={q}",
        "Annonces Médicales": f"https://www.annonces-medicales.com/emploi/recherche?mc={q}",
    }
    jobs = [make_direct_link(name, url) for name, url in sources.items()]
    print(f"  ✓ {len(jobs)} direct links added")
    return jobs

# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
SCRAPERS = [
    fetch_france_travail,   # 1 — official API, fully paginated
    fetch_adzuna,           # 2 — official API (needs ADZUNA_APP_ID + ADZUNA_APP_KEY)
    fetch_jooble,           # 3 — official API (needs JOOBLE_API_KEY)
    fetch_indeed,           # 4 — Apify actor + direct link fallback
    fetch_welcome_jungle,   # 5 — Apify cheerio + direct link fallback
    fetch_glassdoor,        # 6 — Apify actor + direct link fallback
    fetch_linkedin,         # 7 — Apify actor + direct link fallback
    fetch_hellowork,        # 8 — Apify cheerio + direct link fallback
    fetch_staffsante,       # 9 — Apify cheerio + direct link fallback
    fetch_appelmedical,     # 10 — Apify cheerio + direct link fallback
    fetch_vitalis,          # 11 — Apify cheerio + direct link fallback
    fetch_apec,             # 12 — Apify playwright (JS-rendered) + direct link fallback
    fetch_direct_links,     # 13 — direct search links for all dead RSS sources
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
                failed.append(scraper.__name__)
        except Exception as e:
            print(f"  ❌ Error in {scraper.__name__}: {e}")
            failed.append(scraper.__name__)
        time.sleep(1.5)

    print(f"\n✅ Total: {len(all_jobs)} unique jobs from {len(stats)} sources")
    for src, cnt in sorted(stats.items(), key=lambda x: -x[1]):
        status = "✓" if cnt > 0 else "✗"
        print(f"   {status} {src}: {cnt}")

    if failed:
        print(f"\n⚠ Sources with 0 results: {', '.join(failed)}")

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


# ══════════════════════════════════════════════════════════════════════
# REQUIRED: .github/workflows/scrape.yml env block
# Without this, os.environ.get() returns "" and all API sources are skipped.
#
# - name: Run scraper
#   env:
#     FT_CLIENT_ID:     ${{ secrets.FT_CLIENT_ID }}
#     FT_CLIENT_SECRET: ${{ secrets.FT_CLIENT_SECRET }}
#     ADZUNA_APP_ID:    ${{ secrets.ADZUNA_APP_ID }}
#     ADZUNA_APP_KEY:   ${{ secrets.ADZUNA_APP_KEY }}
#     JOOBLE_API_KEY:   ${{ secrets.JOOBLE_API_KEY }}
#     APIFY_API_KEY:    ${{ secrets.APIFY_API_KEY }}
#   run: python scripts/scraper.py
# ══════════════════════════════════════════════════════════════════════
