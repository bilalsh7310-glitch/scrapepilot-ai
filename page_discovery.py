"""ScrapePilot AI — automatic page discovery & classification.

Classify using URL patterns AND page content (never URL alone).
Each result carries a confidence score and a human-readable reason.
Users can correct a category manually in the dashboard.
"""
import re

# (category, url-pattern, content keywords, confidence when URL matches)
_RULES = [
    ("home", [r"^/$", r"^/home/?$", r"^/index"], [], 0.95),
    ("contact", [r"contact", r"get-in-touch", r"reach-us"], ["contact us", "get in touch", "send us a message"], 0.9),
    ("about", [r"about", r"our-story", r"who-we-are", r"company"], ["about us", "who we are", "our story", "company overview"], 0.85),
    ("purpose", [r"purpose", r"mission", r"vision", r"values", r"why-we-exist"], ["our purpose", "our mission", "our vision", "why we exist", "our values"], 0.9),
    ("services", [r"services?$", r"what-we-do", r"solutions?$"], ["our services", "what we do", "services we offer"], 0.85),
    ("service-detail", [r"services?/.+", r"service/.+"], ["service"], 0.6),
    ("products", [r"products?$", r"shop/?$", r"store/?$"], ["our products", "shop"], 0.85),
    ("product-detail", [r"products?/.+", r"product/.+", r"shop/.+"], ["add to cart", "buy now", "in stock"], 0.6),
    ("pricing", [r"pric", r"plans?", r"packages?", r"rates?"], ["pricing", "our plans", "packages"], 0.85),
    ("blog", [r"blog/?$", r"news/?$", r"articles/?$"], ["latest news", "blog", "articles"], 0.85),
    ("blog-article", [r"blog/.+", r"news/.+", r"articles?/.+"], [], 0.6),
    ("faq", [r"faq", r"frequently-asked"], ["frequently asked questions"], 0.9),
    ("team", [r"team", r"our-people", r"staff"], ["meet the team", "our team"], 0.85),
    ("testimonials", [r"testimonial", r"reviews?"], ["testimonials", "what our customers say", "reviews"], 0.85),
    ("locations", [r"locations?", r"branches?", r"areas?/?$", r"area/.+"], ["our locations", "branches", "areas we serve"], 0.8),
    ("portfolio", [r"portfolio", r"projects?/?$", r"work/?$", r"case-stud"], ["portfolio", "our projects", "case studies"], 0.85),
    ("privacy", [r"privacy"], ["privacy policy"], 0.95),
    ("terms", [r"terms", r"conditions"], ["terms and conditions"], 0.95),
]

CATEGORY_LABELS = {
    "home": "Home", "about": "About Us", "purpose": "Purpose / About",
    "services": "Services Overview", "service-detail": "Service Page",
    "products": "Products Overview", "product-detail": "Product Page",
    "contact": "Contact Us", "pricing": "Pricing", "blog": "Blog",
    "blog-article": "Blog Article", "faq": "FAQ", "team": "Team",
    "testimonials": "Testimonials", "locations": "Locations",
    "portfolio": "Portfolio / Projects", "privacy": "Privacy Policy",
    "terms": "Terms & Conditions", "other": "Other",
}


def classify(url, title="", h1_list=None, text=""):
    """Return (category, confidence 0-1, reason)."""
    from urllib.parse import urlparse
    path = urlparse(url).path.lower().rstrip("/") or "/"
    hay = f"{title or ''} {' '.join(h1_list or [])}".lower()
    body = (text or "").lower()

    best = ("other", 0.4, "No URL pattern or content signal matched.")
    for category, patterns, keywords, conf in _RULES:
        url_hit = any(re.search(p, path) for p in patterns)
        kw_hits = [k for k in keywords if k and (k in hay or k in body[:4000])]
        if url_hit and kw_hits:
            score = min(0.97, conf + 0.07)
            reason = (f"URL matches '{category}' and the page mentions "
                      f"'{kw_hits[0]}'.")
            if score > best[1]:
                best = (category, round(score, 2), reason)
        elif url_hit:
            reason = f"URL path '{path}' matches the '{category}' pattern."
            if conf > best[1]:
                best = (category, conf, reason)
        elif kw_hits and conf >= 0.85:
            # Content-only signal, lower confidence than a URL match.
            score = 0.65
            reason = (f"Page content mentions '{kw_hits[0]}' "
                      f"(no URL pattern matched).")
            if score > best[1]:
                best = (category, score, reason)

    # Home is only the site root.
    if path == "/" and best[0] != "home":
        best = ("home", 0.95, "Site root URL.")
    return best


def is_service_page(category):
    return category in ("services", "service-detail")


def is_purpose_page(category):
    return category in ("purpose", "about")


def discover_sitemap_urls(base_url, fetch):
    """Read /sitemap.xml (+ sitemap index) and robots.txt sitemap refs.
    Returns a list of URLs found, or []. fetch is scraper.fetch_url."""
    from urllib.parse import urljoin
    import xml.etree.ElementTree as ET

    found = []

    def _parse_xml(body):
        try:
            root = ET.fromstring(body)
        except Exception:
            return []
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = []
        for loc in root.findall(".//s:loc", ns) or root.findall(".//loc"):
            if loc.text:
                urls.append(loc.text.strip())
        return urls

    for candidate in (urljoin(base_url, "/sitemap.xml"),
                      urljoin(base_url, "/sitemap_index.xml")):
        status, _final, body, err, _r = fetch(candidate)
        if err or status != 200 or not body:
            continue
        urls = _parse_xml(body)
        for u in urls:
            if u.lower().endswith(".xml"):
                st2, _f2, b2, e2, _r2 = fetch(u)
                if not e2 and st2 == 200 and b2:
                    found.extend(_parse_xml(b2))
            else:
                found.append(u)
        if found:
            break
    return found
