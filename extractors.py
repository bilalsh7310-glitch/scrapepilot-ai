"""ScrapePilot AI — extraction of services, products, contact,
purpose/company and blog data from already-scraped pages.

Rule throughout: never invent a service, price, phone number or
purpose statement. Missing fields are reported as "Not Found".
"""
import json
import re
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
SOCIAL_DOMAINS = {
    "facebook.com": "Facebook", "instagram.com": "Instagram",
    "linkedin.com": "LinkedIn", "youtube.com": "YouTube",
    "youtu.be": "YouTube", "twitter.com": "X / Twitter",
    "x.com": "X / Twitter", "tiktok.com": "TikTok",
}


def _first_text(data, limit=300):
    paras = data.get("paragraphs") or []
    for p in paras:
        if len(p) > 40:
            return p[:limit]
    return (data.get("text") or "")[:limit]


def extract_services(pages):
    """One entry per service page, plus a service per H2 on overview pages."""
    services = []
    for page in pages:
        data = page["data"]
        cat = page.get("category") or ""
        if cat not in ("services", "service-detail"):
            continue
        services.append({
            "service_name": (data.get("headings", {}).get("h1") or [""])[0]
                            or page.get("title") or page["url"],
            "url": page["url"],
            "category": cat,
            "description": data.get("meta_description") or _first_text(data),
            "meta_title": data.get("meta_title") or "",
            "meta_description": data.get("meta_description") or "",
            "headings": data.get("headings", {}),
            "features": (data.get("headings", {}).get("h2") or [])[:10],
            "images": data.get("images", [])[:6],
            "internal_links": [l["url"] for l in data.get("internal_links", [])][:10],
            "source_url": page["url"],
            "status": page.get("scrape_status"),
        })
    return services


def extract_products(pages):
    products = []
    for page in pages:
        data = page["data"]
        if (page.get("category") or "") not in ("products", "product-detail"):
            continue
        price = "Not Found"
        m = re.search(r"(AED|USD|GBP|EUR|\$|£|€)\s?[\d,]+(?:\.\d{2})?",
                      data.get("text") or "")
        if m:
            price = m.group(0)
        products.append({
            "product_name": (data.get("headings", {}).get("h1") or [""])[0]
                            or page.get("title") or page["url"],
            "url": page["url"],
            "description": data.get("meta_description") or _first_text(data),
            "price": price,
            "images": data.get("images", [])[:6],
            "structured_data": data.get("json_ld", []),
            "source_url": page["url"],
        })
    return products


def extract_contact(pages):
    """Aggregate public business contact details across all pages,
    keeping the source URL of every value."""
    found = {"emails": {}, "phones": {}, "social": {}, "addresses": {}}
    contact_page_url = "Not Found"
    for page in pages:
        data = page["data"]
        text = data.get("text") or ""
        if (page.get("category") or "") == "contact":
            contact_page_url = page["url"]
        for email in set(EMAIL_RE.findall(text)):
            if not email.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                found["emails"].setdefault(email, page["url"])
        for phone in set(PHONE_RE.findall(text)):
            digits = re.sub(r"\D", "", phone)
            if 7 <= len(digits) <= 15 and len(set(digits)) > 3:
                found["phones"].setdefault(phone.strip(), page["url"])
        for link in data.get("external_links", []):
            host = urlparse(link["url"]).netloc.lower().replace("www.", "")
            label = SOCIAL_DOMAINS.get(host)
            if label:
                found["social"].setdefault(label, link["url"])
        # Address heuristic: a paragraph mentioning a street/area + city.
        for p in data.get("paragraphs", []):
            if re.search(r"\b(street|road|building|tower|mall|avenue|dubai|abu dhabi|sharjah|london|birmingham)\b",
                         p, re.I) and len(p) < 220 and any(
                             c.isdigit() for c in p):
                found["addresses"].setdefault(p.strip(), page["url"])
                break

    def _pack(mapping):
        return [{"value": k, "source_url": v} for k, v in mapping.items()]

    business_name = "Not Found"
    for page in pages:
        og = (page["data"].get("open_graph") or {})
        if og.get("og:site_name"):
            business_name = og["og:site_name"]
            break
    return {
        "business_name": business_name,
        "emails": _pack(found["emails"]) or [{"value": "Not Found", "source_url": ""}],
        "phones": _pack(found["phones"]) or [{"value": "Not Found", "source_url": ""}],
        "whatsapp": [v for v in _pack(found["phones"])
                     if "whatsapp" in (v["value"] or "").lower()] or [],
        "address": _pack(found["addresses"]) or [{"value": "Not Found", "source_url": ""}],
        "social": [{"platform": k, "url": v} for k, v in found["social"].items()]
                  or [{"platform": "Not Found", "url": ""}],
        "contact_page_url": contact_page_url,
        "opening_hours": "Not Found",
    }


def extract_purpose(pages):
    """Purpose / About pages, kept separate — never merged into one."""
    out = []
    for page in pages:
        data = page["data"]
        if (page.get("category") or "") not in ("purpose", "about"):
            continue
        text = data.get("text") or ""
        mission = vision = ""
        for para in data.get("paragraphs", []):
            low = para.lower()
            if not mission and "mission" in low:
                mission = para[:500]
            if not vision and "vision" in low:
                vision = para[:500]
        out.append({
            "page_title": page.get("title") or page["url"],
            "url": page["url"],
            "purpose_statement": _first_text(data, 600) if text else "Not Found",
            "mission": mission or "Not Found",
            "vision": vision or "Not Found",
            "headings": data.get("headings", {}),
            "source_url": page["url"],
        })
    return out


def extract_company(pages):
    info = {"company_name": "Not Found", "overview": "Not Found",
            "history": "Not Found", "values": [], "source_url": ""}
    for page in pages:
        data = page["data"]
        if (page.get("category") or "") not in ("about", "purpose", "home"):
            continue
        og = data.get("open_graph") or {}
        if info["company_name"] == "Not Found" and og.get("og:site_name"):
            info["company_name"] = og["og:site_name"]
        if info["overview"] == "Not Found":
            info["overview"] = data.get("meta_description") or _first_text(data, 600)
        info["source_url"] = page["url"]
        for h in (data.get("headings", {}).get("h2") or []):
            if any(k in h.lower() for k in ("value", "mission", "vision", "history", "story")):
                info["values"].append(h)
        if info["overview"] != "Not Found" and info["company_name"] != "Not Found":
            break
    if info["company_name"] == "Not Found":
        # Fall back to the home page title.
        for page in pages:
            if (page.get("category") or "") == "home" and page.get("title"):
                info["company_name"] = page["title"].split("|")[0].split("-")[0].strip()
                break
    return info


def extract_blogs(pages):
    blogs = []
    for page in pages:
        data = page["data"]
        if (page.get("category") or "") != "blog-article":
            continue
        blogs.append({
            "title": page.get("title") or page["url"],
            "url": page["url"],
            "author": "Not Found",
            "published": "Not Found",
            "headings": data.get("headings", {}),
            "excerpt": _first_text(data, 300),
            "featured_image": (data.get("images") or [{}])[0].get("url", ""),
            "meta_title": data.get("meta_title") or "",
            "meta_description": data.get("meta_description") or "",
            "source_url": page["url"],
        })
    return blogs


def summarize_session(pages):
    """Real statistics only — calculated from stored results."""
    ok = [p for p in pages if p.get("scrape_status") == "success"]
    failed = [p for p in pages if p.get("scrape_status") != "success"]
    cats = {}
    for p in pages:
        cats[p.get("category") or "other"] = cats.get(p.get("category") or "other", 0) + 1
    return {
        "total_discovered": len(pages),
        "total_scraped": len(ok),
        "successful": len(ok),
        "failed": len(failed),
        "services_pages": cats.get("services", 0) + cats.get("service-detail", 0),
        "services_found": len(extract_services(pages)),
        "products_found": len(extract_products(pages)),
        "purpose_pages": cats.get("purpose", 0) + cats.get("about", 0),
        "blog_articles": cats.get("blog-article", 0),
        "internal_links": sum(len(p["data"].get("internal_links", [])) for p in pages),
        "external_links": sum(len(p["data"].get("external_links", [])) for p in pages),
        "images": sum(len(p["data"].get("images", [])) for p in pages),
        "contact_fields": sum(
            1 for v in extract_contact(pages).values()
            if isinstance(v, list) and v and v[0].get("value") != "Not Found"
        ),
        "by_category": cats,
    }
