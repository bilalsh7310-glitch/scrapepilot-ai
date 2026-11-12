"""ScrapePilot AI — configuration.

All settings come from environment variables (see .env.example).
No secrets are stored here or in the database.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- OpenRouter (AI layer is optional; scraping works without it) ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
).strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# --- Crawl defaults (safe, sensible; the browser cannot raise them
#     above the server-side caps in MAX_* below) ---
DEFAULT_MAX_PAGES = int(os.environ.get("SCRAPEPILOT_MAX_PAGES", "25"))
DEFAULT_MAX_DEPTH = int(os.environ.get("SCRAPEPILOT_MAX_DEPTH", "2"))
DEFAULT_TIMEOUT = float(os.environ.get("SCRAPEPILOT_TIMEOUT", "15"))
DEFAULT_DELAY = float(os.environ.get("SCRAPEPILOT_DELAY", "0.5"))

# --- Hard server-side caps (never trust browser-supplied limits) ---
MAX_PAGES_CAP = 200
MAX_DEPTH_CAP = 4
MAX_TIMEOUT_CAP = 60
MIN_DELAY = 0.0
MAX_DELAY = 10.0
MAX_RESPONSE_BYTES = 2_000_000          # 2 MB per page
MAX_REDIRECTS = 5

# --- Storage ---
DATABASE_PATH = os.path.join(BASE_DIR, "instance", "scrapepilot.db")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")

# --- Flask ---
HOST = os.environ.get("SCRAPEPILOT_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", os.environ.get("SCRAPEPILOT_PORT", "5000")))
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "scrapepilot-dev-key-change-me")
MAX_CONTENT_LENGTH = 1 * 1024 * 1024     # 1 MB request bodies

USER_AGENT = (
    "ScrapePilotAI/1.0 (+https://github.com/scrapepilot-ai; "
    "respectful crawler, honours robots.txt)"
)

# --- Portfolio profile (section 21 of the master prompt).
#     Only the facts the user supplied. No employers, dates or
#     durations are invented. Kept separate from scraped data. ---
PORTFOLIO_PROFILE = {
    "name": "Bilal",
    "background": "SEO and Digital Marketing",
    "skills": [
        "Keyword Research", "On Page SEO", "Technical SEO", "Off Page SEO",
        "AEO", "GEO", "Content Optimization", "Website Analysis",
    ],
    "technical_interests": ["Python", "HTML", "CSS", "JavaScript"],
    "experience": "Practical SEO internship and professional SEO work",
    "projects": [
        "Elite Module Repair", "Quick Vehicle Keys", "Eastern Balti Map",
        "Aysa Furniture Assembly", "GRK Chauffeur", "GLIF Medical",
    ],
    "education": "Associate Degree in Computer Science",
}
