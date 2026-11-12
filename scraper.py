"""ScrapePilot AI — single-page fetcher with SSRF protection.

Security (master prompt section 22):
- only http/https
- rejects localhost, private, loopback, link-local, multicast,
  reserved and internal IP ranges, and the cloud metadata address
- resolves the hostname and validates every resolved IP
- re-validates every redirect destination
- connection/read timeouts, per-page response-size limit
- honours robots.txt via the caller (crawler), robots meta here
"""
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import config

_BLOCKED_HOSTS = {"metadata.google.internal"}
_METADATA_IP = ipaddress.ip_address("169.254.169.254")


def _ip_is_safe(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr == _METADATA_IP:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_url(url):
    """Return (ok, error). Raises nothing."""
    if not url or not isinstance(url, str):
        return False, "URL is empty."
    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL could not be parsed."
    if parsed.scheme not in ("http", "https"):
        return False, "Only http:// and https:// URLs are allowed."
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "URL has no host."
    if host in _BLOCKED_HOSTS or host.endswith(".internal"):
        return False, "That host is blocked."
    # Literal IP in the URL — only check it when the host actually is an IP.
    # (Hostnames are checked after DNS resolution below.)
    try:
        ipaddress.ip_address(host)
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False
    if is_literal_ip and not _ip_is_safe(host):
        return False, "That IP address is private or reserved."
    # Resolve the hostname and check every resolved address.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, f"Could not resolve host '{host}'."
    except Exception as exc:
        return False, f"DNS lookup failed: {exc}"
    if not infos:
        return False, f"Could not resolve host '{host}'."
    for info in infos:
        if not _ip_is_safe(info[4][0]):
            return False, (
                f"Host '{host}' resolves to a private or reserved IP "
                f"({info[4][0]})."
            )
    return True, ""


def _check_size(resp):
    length = resp.headers.get("Content-Length")
    if length and int(length) > config.MAX_RESPONSE_BYTES:
        raise ValueError(
            f"Response too large ({length} bytes, limit "
            f"{config.MAX_RESPONSE_BYTES})."
        )


def fetch_url(url, timeout=None, session=None):
    """Fetch one URL, following redirects manually so each hop is
    re-validated. Returns (status_code, final_url, html, error, redirects).
    Never raises for HTTP errors — those are data, not crashes."""
    timeout = timeout or config.DEFAULT_TIMEOUT
    ok, err = validate_url(url)
    if not ok:
        return None, url, "", err, []
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": config.USER_AGENT})
    current, redirects = url, []
    try:
        for _ in range(config.MAX_REDIRECTS + 1):
            resp = sess.get(
                current, timeout=timeout, allow_redirects=False, stream=True
            )
            _check_size(resp)
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                resp.close()
                if not location:
                    return resp.status_code, current, "", "Redirect with no Location header.", redirects
                nxt = urljoin(current, location)
                ok2, err2 = validate_url(nxt)
                if not ok2:
                    return None, current, "", f"Redirect blocked: {err2}", redirects
                redirects.append({"from": current, "to": nxt,
                                  "status": resp.status_code})
                current = nxt
                continue
            # Read body with a size cap.
            chunks, total = [], 0
            for chunk in resp.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > config.MAX_RESPONSE_BYTES:
                    resp.close()
                    return resp.status_code, current, "", (
                        "Response exceeded the 2 MB size limit."
                    ), redirects
                chunks.append(chunk)
            resp.close()
            body = b"".join(chunks)
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" not in ctype and "text/" not in ctype and "xml" not in ctype:
                return resp.status_code, current, "", (
                    f"Skipped non-HTML content ({ctype or 'unknown type'})."
                ), redirects
            return resp.status_code, current, body.decode(
                resp.encoding or "utf-8", errors="replace"
            ), "", redirects
        return None, current, "", "Too many redirects.", redirects
    except requests.exceptions.Timeout:
        return None, current, "", f"Timed out after {timeout}s.", redirects
    except requests.exceptions.SSLError as exc:
        return None, current, "", f"SSL error: {exc}", redirects
    except requests.exceptions.RequestException as exc:
        return None, current, "", f"Request failed: {exc}", redirects
    except ValueError as exc:
        return None, current, "", str(exc), redirects


def parse_page(url, html, status_code):
    """Extract everything section 2 of the prompt asks for."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    def meta(name=None, prop=None):
        tag = None
        if name:
            tag = soup.find("meta", attrs={"name": name})
        if tag is None and prop:
            tag = soup.find("meta", attrs={"property": prop})
        return (tag.get("content", "").strip() if tag else "")

    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    canonical_tag = soup.find("link", rel="canonical")
    canonical = canonical_tag.get("href", "").strip() if canonical_tag else ""

    headings = {}
    for level in range(1, 7):
        headings[f"h{level}"] = [
            h.get_text(" ", strip=True)
            for h in soup.find_all(f"h{level}")
            if h.get_text(strip=True)
        ]

    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if p.get_text(strip=True)
    ]
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    internal, external = [], []
    base_host = urlparse(url).netloc.lower()
    seen_links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full = urljoin(url, href).split("#")[0]
        if full in seen_links:
            continue
        seen_links.add(full)
        entry = {"url": full, "text": a.get_text(" ", strip=True)[:120]}
        if urlparse(full).netloc.lower() == base_host:
            internal.append(entry)
        else:
            external.append(entry)

    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        images.append({
            "url": urljoin(url, src),
            "alt": (img.get("alt") or "").strip(),
        })

    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr")[:20]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)

    json_ld = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or ""
        if raw.strip():
            json_ld.append(raw.strip()[:5000])

    og = {}
    for tag in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
        og[tag["property"]] = (tag.get("content") or "").strip()

    return {
        "url": url,
        "title": title,
        "meta_title": title,
        "meta_description": meta("description"),
        "meta_keywords": meta("keywords"),
        "canonical": canonical,
        "robots_meta": meta("robots"),
        "open_graph": og,
        "json_ld": json_ld,
        "headings": headings,
        "paragraphs": paragraphs[:200],
        "text": text[:20000],
        "internal_links": internal,
        "external_links": external,
        "images": images,
        "tables": tables,
        "status_code": status_code,
    }
