"""ScrapePilot AI — SEO analysis of the crawled pages.

Every finding carries the affected URL, evidence and an explanation.
Measured findings are kept separate from suggestions. This is a crawl
audit only — it never claims to measure Core Web Vitals, rankings,
traffic, backlinks or search volume.
"""
from urllib.parse import urlparse


def _finding(severity, check, url, evidence, explanation, kind="finding"):
    return {"severity": severity, "check": check, "url": url,
            "evidence": evidence, "explanation": explanation, "kind": kind}


def analyze(pages, base_url):
    findings = []
    titles, descriptions = {}, {}
    base_host = urlparse(base_url).netloc.lower()

    for page in pages:
        data = page["data"]
        url = page["url"]
        if page.get("scrape_status") != "success":
            findings.append(_finding(
                "High", "Page failed to load", url,
                page.get("error") or f"HTTP {page.get('status_code')}",
                "The page could not be fetched, so none of its content "
                "could be checked. Fix the server error or the blocking "
                "rule before anything else on this page matters."))
            continue
        title = (data.get("meta_title") or "").strip()
        desc = (data.get("meta_description") or "").strip()
        h1s = data.get("headings", {}).get("h1", [])

        if not title:
            findings.append(_finding("Critical", "Missing title tag", url,
                "No <title> element found.",
                "Every page needs a unique title tag — it is what Google "
                "shows in search results. Without one the page is much "
                "less likely to rank or be clicked."))
        else:
            if len(title) > 60:
                findings.append(_finding("Medium", "Title too long", url,
                    f"{len(title)} characters: “{title[:80]}”",
                    "Titles over about 60 characters are cut off in "
                    "Google search results. Shorten it to the main keyword "
                    "plus brand."))
            titles.setdefault(title.lower(), []).append(url)
        if not desc:
            findings.append(_finding("High", "Missing meta description", url,
                "No meta description found.",
                "Without a meta description Google writes its own snippet, "
                "which is usually less persuasive. Add one of about "
                "150–155 characters."))
        else:
            if len(desc) > 160:
                findings.append(_finding("Low", "Meta description too long", url,
                    f"{len(desc)} characters.",
                    "Descriptions over about 160 characters are cut off in "
                    "search results."))
            descriptions.setdefault(desc.lower(), []).append(url)
        if not h1s:
            findings.append(_finding("High", "Missing H1 heading", url,
                "No <h1> found on the page.",
                "Each page should have exactly one H1 that states its main "
                "topic. Without one, Google and readers have to guess what "
                "the page is about."))
        elif len(h1s) > 1:
            findings.append(_finding("Medium", "Multiple H1 headings", url,
                f"{len(h1s)} H1s: {', '.join(h1s[:3])}",
                "Use one H1 per page for the main topic; turn the others "
                "into H2s."))
        if not data.get("canonical"):
            findings.append(_finding("Low", "Missing canonical tag", url,
                "No <link rel=\"canonical\"> found.",
                "A canonical tag tells Google which URL is the main version "
                "of the page and prevents duplicate-content confusion."))
        missing_alt = [i for i in data.get("images", []) if not i.get("alt")]
        if missing_alt:
            findings.append(_finding("Medium", "Images missing ALT text", url,
                f"{len(missing_alt)} of {len(data['images'])} images have no alt text.",
                "Alt text helps Google understand images and helps screen "
                "readers. Add short, descriptive alt text to each image."))
        if not data.get("json_ld"):
            findings.append(_finding("Low", "No Schema.org markup", url,
                "No JSON-LD structured data found.",
                "Schema markup (for example LocalBusiness or FAQPage) can "
                "earn rich results in Google. It is optional, not a ranking "
                "penalty on its own."))
        status = page.get("status_code")
        if status and status >= 400:
            findings.append(_finding("Critical", "Broken page (HTTP error)", url,
                f"HTTP {status}",
                "The page returns an error status. Search engines drop "
                "error pages from results — fix or redirect it."))
        for r in data.get("redirects", []) if isinstance(data.get("redirects"), list) else []:
            findings.append(_finding("Low", "Redirect", url,
                f"{r.get('status')} → {r.get('to')}",
                "The URL redirects elsewhere. Update internal links to "
                "point at the final URL."))

    for title, urls in titles.items():
        if len(urls) > 1:
            findings.append(_finding("High", "Duplicate title tag", urls[0],
                f"“{title[:80]}” is used on {len(urls)} pages: {', '.join(urls[:3])}",
                "Each page needs its own title. Duplicate titles make "
                "Google treat the pages as near-duplicates."))
    for desc, urls in descriptions.items():
        if len(urls) > 1:
            findings.append(_finding("Medium", "Duplicate meta description", urls[0],
                f"The same description is used on {len(urls)} pages.",
                "Write a unique description for each page that describes "
                "what that page offers."))

    # Sitemap availability — measured, not guessed.
    has_sitemap = any("sitemap" in (p["url"] or "") for p in pages)
    if not has_sitemap:
        findings.append(_finding("Low", "Sitemap not found in crawl", base_url,
            "No sitemap.xml URL was discovered during the crawl.",
            "A sitemap at /sitemap.xml helps Google discover new pages. "
            "This check only covers what the crawl found — confirm the "
            "file exists if the site uses a different sitemap path.",
            kind="suggestion"))

    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    counts["Passed"] = max(0, len(pages) * 6 - len(findings))
    return {"findings": findings, "counts": counts,
            "pages_checked": len(pages)}
