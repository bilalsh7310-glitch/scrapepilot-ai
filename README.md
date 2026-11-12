# ScrapePilot AI

A real website scraping and data extraction platform. Enter one website URL,
click **Start Scraping**, and ScrapePilot AI discovers the site's permitted
public pages, extracts the data, and shows it in one dashboard — no fake
statistics, no invented results.

**Always-visible sections:** Services Pages, Contact Information and
Purpose / About Pages. If a website has no matching page or data, the section
stays visible and says **Not Found** / **No matching page discovered**.

## Run locally (Windows, Python 3.11.9)

```bat
start.bat
```

Or manually:

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open http://127.0.0.1:5000

## AI assistant (optional)

Scraping works fully without a key. For the AI assistant, add a free key to
`.env` (from https://openrouter.ai/keys):

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free
```

The key is read only by the Python backend and never reaches the browser.
The assistant answers only from the current session's extracted data, and
says when information is missing. It can also answer questions about Bilal's
portfolio profile (SEO & Digital Marketing), kept separate from scraped data.

## What it does

- Validates the URL and blocks SSRF targets (localhost, private/reserved IPs,
  cloud metadata endpoints); re-validates every redirect.
- Respects `robots.txt`, reads `sitemap.xml`, discovers internal pages from
  navigation, footer, content and sitemap.
- Crawls one domain only, BFS, with server-side caps (default 25 pages,
  depth 2; caps: 200 pages, depth 4).
- Extracts per page: title, meta title/description/keywords, H1–H6, text,
  internal/external links, images + ALT, tables, canonical, robots meta,
  Open Graph, JSON-LD, status code, redirects, category + reason.
- Classifies pages from URL patterns **and** page content, with a confidence
  score; categories can be corrected manually in the dashboard.
- Extracts services, products, public contact details (with source URL per
  value), purpose/mission/vision, company info and blog articles.
- Runs technical SEO checks (missing/duplicate titles and descriptions,
  missing/multiple H1, missing ALT, missing canonical, broken pages,
  redirects, sitemap, schema) with Critical/High/Medium/Low severity.
- Background jobs with real progress polling; history in SQLite.
- Exports the complete report (including empty required sections) as
  CSV, JSON or TXT.

## Tests

```bat
.venv\Scripts\activate
python -m pytest tests/ -q
```

Tests cover URL validation and SSRF protection, robots.txt handling,
sitemap discovery, duplicate removal, page classification, the three
mandatory sections, extraction, SEO checks, SQLite storage, progress
polling, exports, and a full end-to-end scrape against a local test site
(the test server is allowed only inside the test run).

## Deploy on Render

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Environment variables: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (optional)

**Persistence note:** history is stored in SQLite on the local disk
(`instance/scrapepilot.db`). On Render's free tier the filesystem is
temporary, so history is lost on redeploy/restart unless you add a
persistent disk or an external database.

## Project structure

```
app.py            Flask app, background jobs, API, exports
config.py         Settings, limits, caps, portfolio profile
crawler.py        BFS crawl, robots.txt, sitemap seeding
scraper.py        URL validation + SSRF protection, page fetch/parse
page_discovery.py Page classification + sitemap parsing
extractors.py     Services / products / contact / purpose / company / blog
seo_analyzer.py   Technical SEO checks
ai_assistant.py   OpenRouter client (optional)
database.py       SQLite sessions / pages / exports
templates/index.html   Single-page dashboard
static/css/style.css   Dark/light theme
static/js/script.js    Fetch API, polling, tabs, tables, chat
```

## Troubleshooting

- **Every URL is rejected with "resolves to a private or reserved IP
  (198.18.x.x)"**: your network's DNS resolver is returning CGNAT /
  benchmarking addresses for all hosts. Use a normal DNS resolver
  (for example your ISP's or 8.8.8.8) — the check is working as designed.
- **A site returns no pages**: it may block bots, require login, or
  disallow crawling in robots.txt. ScrapePilot reports the reason per page
  and never tries to bypass the block.
- **AI says the key is not set**: copy `.env.example` to `.env`, add your
  free key, and restart the app.
