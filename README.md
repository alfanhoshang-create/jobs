# 🦷 Assistant Dentaire — Job Search Agent

Searches 20 job sites every day at 10h00 (Paris time), builds a beautiful viewer page, and sends you the link on WhatsApp.

---

## 🗂 Project Structure

```
dental-job-agent/
├── .github/
│   └── workflows/
│       └── daily_search.yml     ← GitHub Actions (runs daily, free)
├── scripts/
│   ├── scraper.py               ← Fetches jobs from all 20 sources
│   ├── build_html.py            ← Builds the viewer HTML page
│   └── notify_whatsapp.py       ← Sends WhatsApp message
├── docs/
│   ├── index.html               ← Your viewer page (auto-generated)
│   └── jobs.json                ← Raw job data (auto-generated)
└── README.md
```

---

## 🚀 Setup (one time, ~15 minutes)

### Step 1 — Create GitHub repository

1. Go to [github.com](https://github.com) → **New repository**
2. Name it `jobs` (your URL will be `https://yourname.github.io/jobs/`)
3. Set it to **Public**
4. Upload all these files

### Step 2 — Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main` / folder: `/docs`
4. Click **Save**

Your page will be live at: `https://YOURNAME.github.io/jobs/`

### Step 3 — Add API keys as GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these secrets:

| Secret name | Where to get it |
|---|---|
| `FT_CLIENT_ID` | [francetravail.io](https://francetravail.io) → create app → Client ID |
| `FT_CLIENT_SECRET` | Same app → Client Secret |
| `ADZUNA_APP_ID` | [developer.adzuna.com](https://developer.adzuna.com) → register free |
| `ADZUNA_APP_KEY` | Same registration |
| `JOOBLE_API_KEY` | Email api@jooble.org with your site URL, get key |
| `WHATSAPP_NUMBER` | Your number: `+33612345678` |
| `CALLMEBOT_API_KEY` | See Step 4 below |

### Step 4 — Set up CallMeBot (WhatsApp, free)

1. Save this number in your phone contacts: **+34 644 59 77 87** (name it "CallMeBot")
2. Send this exact WhatsApp message to that number:
   ```
   I allow callmebot to send me messages
   ```
3. Within a few seconds you'll receive your **API key** by WhatsApp
4. Add it as the `CALLMEBOT_API_KEY` secret in GitHub

### Step 5 — Add future API keys (when ready)

When you get your Jooble key, just add it as `JOOBLE_API_KEY` secret.
The scraper automatically skips any source whose key is missing — no errors.

### Step 6 — Test it manually

1. Go to your repo → **Actions** tab
2. Click **🦷 Daily Dental Job Search**
3. Click **Run workflow** → **Run workflow**
4. Watch it run (takes ~2-3 minutes)
5. Check your WhatsApp for the link!

---

## 📊 Sources covered

| # | Source | Method | Notes |
|---|---|---|---|
| 1 | France Travail | Official API | Requires FT_CLIENT_ID + FT_CLIENT_SECRET |
| 2 | Adzuna | Official API | Requires ADZUNA_APP_ID + ADZUNA_APP_KEY |
| 3 | Jooble | Official API | Requires JOOBLE_API_KEY |
| 4 | Indeed | RSS feed | Free, no key needed |
| 5 | Welcome to the Jungle | RSS feed | Free |
| 6 | Meteojob | RSS feed | Free |
| 7 | Option Carrière | RSS feed | Free |
| 8 | Talent.com | RSS feed | Free |
| 9 | Jobijoba | RSS feed | Free |
| 10 | APEC | Public API | Free |
| 11 | Staffsanté | RSS feed | Free |
| 12 | Appel Médical | RSS feed | Free |
| 13 | Vitalis Médical | RSS feed | Free |
| 14 | Dental Emploi | HTML scrape | Free |
| 15 | Annonces Médicales | RSS feed | Free |
| 16 | Emploi Ouest-France | RSS feed | Free |
| 17 | Moovijob | RSS feed | Free |
| 18 | HelloWork | RSS feed | Free |
| 19 | Glassdoor | Direct link* | Blocks bots |
| 20 | LinkedIn | Direct link* | Blocks bots |

*Glassdoor and LinkedIn show a direct link to their search results since they block automated access.

---

## 💰 Total cost: $0/month

- GitHub Actions: free (2,000 min/month, job takes ~3 min/day = ~90 min/month)
- GitHub Pages: free
- CallMeBot: free
- All APIs: free tiers used

---

## 🔧 Customization

### Change job keywords
In `scripts/scraper.py`, line 13:
```python
KEYWORDS = "assistant dentaire"
```

### Change max jobs per source
In `scripts/scraper.py`, line 15:
```python
MAX_PER_SOURCE = 100
```

### Change run time
In `.github/workflows/daily_search.yml`:
```yaml
- cron: '0 8 * * *'   # 08:00 UTC = 10:00 Paris (winter)
```
Use [crontab.guru](https://crontab.guru) to adjust.

### Add Apify for LinkedIn/Glassdoor (optional)
When you get Apify credits, add `APIFY_TOKEN` as a secret and the scraper can be extended to use Apify actors for those blocked sites.
