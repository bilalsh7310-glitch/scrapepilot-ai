"""ScrapePilot AI — the crawler (section 2/3 of the master prompt).

Breadth-first crawl of one domain:
- seeds: the start URL + sitemap URLs + robots.txt sitemap refs
- respects robots.txt (urllib.robotparser) and the per-page delay
- normalises URLs, strips fragments, de-duplicates
- stops at max_pages / max_depth / domain boundary
- one failed page never fails the whole crawl
- progress is reported through a callback with real job state
"""
import time
from urllib.parse import urldefrag, urljoin, urlparse
from urllib import robotparser

import requests

import config
import page_discovery
from scraper import fetch_url, parse_page, validate_url


def _normalize(url):
    url, _frag = urldefrag(url.strip())
    parsed = urlparse(url)
    if parsed.path == "":
        url = url + "/"
    return url


def _same_domain(url, base_host):
    return urlparse(url).netloc.lower() == base_host


def crawl(start_url, settings, progress=None, stop_check=None):
    """Run a crawl. Returns (pages, stats). pages are dicts ready for
    database.save_page. progress(state_dict) is called after each page."""
    max_pages = settings["max_pages"]
    max_depth = settings["max_depth"]
    timeout = settings["timeout"]
    delay = settings["delay"]
    include = settings.get("include_patterns") or []
    exclude = settings.get("exclude_patterns") or []
    base_host = urlparse(start_url).netloc.lower()

    session = requests.Session()
    rp = robotparser.RobotFileParser()
    rp.set_url(urljoin(start_url, "/robots.txt"))
    try:
        rp.read()
    except Exception:
        rp = None

    def allowed(url):
        if rp is not None:
            try:
                if not rp.can_fetch(config.USER_AGENT, url):
                    return False
            except Exception:
                pass
        return True

    def wanted(url):
        path = urlparse(url).path.lower()
        if include and not any(p.lower() in path for p in include):
            return False
        if any(p.lower() in path for p in exclude):
            return False
        return True

    queue = [(start_url, 0)]
    seen, pages = set(), []
    skipped_robots = skipped_limits = 0

    # Seed with the sitemap so discovery does not stop at the homepage.
    try:
        for sitemap_url in page_discovery.discover_sitemap_urls(
                start_url, lambda u: fetch_url(u, timeout=timeout, session=session)):
            norm = _normalize(sitemap_url)
            if _same_domain(norm, base_host) and norm not in seen and wanted(norm):
                queue.append((norm, 1))
    except Exception:
        pass

    while queue and len(pages) < max_pages:
        if stop_check and stop_check():
            break
        url, depth = queue.pop(0)
        norm = _normalize(url)
        if norm in seen or depth > max_depth:
            continue
        seen.add(norm)
        if not allowed(norm):
            skipped_robots += 1
            continue
        if progress:
            progress({"phase": "fetching", "current_url": norm,
                      "done": len(pages), "queued": len(queue),
                      "max_pages": max_pages})
        status, final_url, html, error, redirects = fetch_url(
            norm, timeout=timeout, session=session)
        if error or status is None or not html:
            pages.append({
                "url": norm, "title": "", "meta_title": "",
                "meta_description": "", "category": "other",
                "category_confidence": 0.0,
                "category_reason": "Page could not be fetched.",
                "status_code": status, "scrape_status": "failed",
                "error": error or f"HTTP {status}", "data": {},
            })
        else:
            data = parse_page(final_url, html, status)
            data["redirects"] = redirects
            category, conf, reason = page_discovery.classify(
                final_url, data["title"],
                data["headings"].get("h1", []), data["text"])
            pages.append({
                "url": final_url, "title": data["title"],
                "meta_title": data["meta_title"],
                "meta_description": data["meta_description"],
                "category": category, "category_confidence": conf,
                "category_reason": reason, "status_code": status,
                "scrape_status": "success", "error": "", "data": data,
            })
            if depth < max_depth:
                for link in data["internal_links"]:
                    nxt = _normalize(link["url"])
                    if (nxt not in seen and _same_domain(nxt, base_host)
                            and wanted(nxt)):
                        queue.append((nxt, depth + 1))
        if delay:
            time.sleep(delay)
        if progress:
            progress({"phase": "fetching", "current_url": norm,
                      "done": len(pages), "queued": len(queue),
                      "max_pages": max_pages})

    stats = {
        "discovered": len(pages),
        "successful": sum(1 for p in pages if p["scrape_status"] == "success"),
        "failed": sum(1 for p in pages if p["scrape_status"] != "success"),
        "skipped_robots": skipped_robots,
        "skipped_limits": skipped_limits,
        "max_pages": max_pages,
        "max_depth": max_depth,
    }
    return pages, stats
