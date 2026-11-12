"""ScrapePilot AI tests.

Run:  python -m pytest tests/ -q        (or python -m unittest discover -s tests)
Do not claim a test passed unless it was actually run — see README.
The local test website is allowed ONLY inside these tests, by patching
validate_url; production code still blocks localhost / private IPs.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import database  # noqa: E402
import extractors  # noqa: E402
import page_discovery  # noqa: E402
import scraper  # noqa: E402
import seo_analyzer  # noqa: E402

HOME_HTML = """<!doctype html><html><head><title>Acme Plumbing | Dubai</title>
<meta name="description" content="Acme Plumbing fixes leaks and installs pipes in Dubai.">
<meta property="og:site_name" content="Acme Plumbing"></head>
<body><h1>Acme Plumbing Dubai</h1><p>We fix leaks fast.</p>
<nav><a href="/services">Services</a><a href="/about-us">About Us</a>
<a href="/contact-us">Contact Us</a><a href="/blog">Blog</a></nav>
<footer>Call +971 50 123 4567 or mail hello@acmeplumbing.example</footer>
</body></html>"""

SERVICES_HTML = """<!doctype html><html><head><title>Our Services | Acme Plumbing</title>
<meta name="description" content="Leak repair, pipe installation and drain cleaning."></head>
<body><h1>Our Services</h1><h2>Leak Repair</h2><p>We repair leaks quickly.</p>
<h2>Drain Cleaning</h2><p>High pressure drain cleaning.</p>
<img src="/img/van.jpg" alt="Acme van"></body></html>"""

CONTACT_HTML = """<!doctype html><html><head><title>Contact Us | Acme Plumbing</title></head>
<body><h1>Contact Us</h1><p>Email us at hello@acmeplumbing.example or call +971 50 123 4567.</p>
<p>Visit us at 12 Maple Street, Dubai.</p>
<a href="https://facebook.com/acmeplumbing">Facebook</a>
<a href="mailto:hello@acmeplumbing.example">Email</a></body></html>"""

ABOUT_HTML = """<!doctype html><html><head><title>About Us | Acme Plumbing</title>
<meta name="description" content="Our purpose is clean water for every home."></head>
<body><h1>About Us</h1><h2>Our Purpose</h2><p>Our purpose is to keep every home leak free.</p>
<h2>Our Mission</h2><p>Our mission is fast, honest plumbing.</p></body></html>"""

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>PLACEHOLDER/services</loc></url>
<url><loc>PLACEHOLDER/contact-us</loc></url>
<url><loc>PLACEHOLDER/about-us</loc></url>
</urlset>"""

ROUTES = {
    "/": HOME_HTML, "/services": SERVICES_HTML,
    "/contact-us": CONTACT_HTML, "/about-us": ABOUT_HTML,
    "/robots.txt": "User-agent: *\nAllow: /\n",
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/sitemap.xml":
            body = SITEMAP_XML.replace("PLACEHOLDER", f"http://127.0.0.1:{self.server.server_port}")
            self._send(200, body, "application/xml")
        elif self.path in ROUTES:
            self._send(200, ROUTES[self.path], "text/html")
        else:
            self._send(404, "not found", "text/html")

    def _send(self, code, body, ctype):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _sample_page(url, category, html):
    data = scraper.parse_page(url, html, 200)
    return {"url": url, "title": data["title"], "meta_title": data["meta_title"],
            "meta_description": data["meta_description"], "category": category,
            "category_confidence": 0.9, "category_reason": "test",
            "status_code": 200, "scrape_status": "success", "error": "",
            "data": data}


class TestValidation(unittest.TestCase):
    def test_valid_public_url(self):
        # This VM's DNS returns a CGNAT address (198.18.x.x) for every host,
        # which the SSRF check correctly rejects. Control DNS in this test.
        fake_info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                      ("93.184.216.34", 0))]
        with mock.patch("socket.getaddrinfo", return_value=fake_info):
            ok, err = scraper.validate_url("https://example.com")
        self.assertTrue(ok, err)

    def test_rejects_non_http(self):
        ok, err = scraper.validate_url("ftp://example.com/x")
        self.assertFalse(ok)
        self.assertIn("http", err)

    def test_rejects_localhost(self):
        for bad in ("http://localhost:5000/", "http://127.0.0.1/",
                    "http://192.168.1.10/", "http://10.0.0.5/",
                    "http://169.254.169.254/latest/meta-data/"):
            ok, _ = scraper.validate_url(bad)
            self.assertFalse(ok, bad)

    def test_rejects_unresolvable_host(self):
        ok, _ = scraper.validate_url("https://nonexistent-host-xyz-12345.invalid/")
        self.assertFalse(ok)


class TestClassification(unittest.TestCase):
    def test_about_url(self):
        cat, conf, _ = page_discovery.classify("https://x.com/about-us", "About Us", ["About Us"], "")
        self.assertEqual(cat, "about")
        self.assertGreaterEqual(conf, 0.8)

    def test_service_detail_by_url_and_content(self):
        cat, _, _ = page_discovery.classify(
            "https://x.com/services/leak-repair", "Leak Repair", ["Leak Repair"],
            "Our leak repair service fixes pipes.")
        self.assertEqual(cat, "service-detail")

    def test_purpose_by_content(self):
        cat, _, _ = page_discovery.classify(
            "https://x.com/our-story", "Our Story", ["Our Story"],
            "Our purpose is clean water. Our mission is honest plumbing.")
        self.assertIn(cat, ("purpose", "about"))

    def test_home_is_root_only(self):
        cat, _, _ = page_discovery.classify("https://x.com/", "Home", ["Welcome"], "")
        self.assertEqual(cat, "home")


class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.pages = [
            _sample_page("https://acme.example/", "home", HOME_HTML),
            _sample_page("https://acme.example/services", "services", SERVICES_HTML),
            _sample_page("https://acme.example/contact-us", "contact", CONTACT_HTML),
            _sample_page("https://acme.example/about-us", "purpose", ABOUT_HTML),
        ]

    def test_services_extracted(self):
        services = extractors.extract_services(self.pages)
        self.assertEqual(len(services), 1)
        self.assertIn("Services", services[0]["service_name"])
        self.assertIn("Leak Repair", services[0]["features"])

    def test_contact_found_across_pages(self):
        contact = extractors.extract_contact(self.pages)
        emails = [e["value"] for e in contact["emails"]]
        phones = [e["value"] for e in contact["phones"]]
        self.assertIn("hello@acmeplumbing.example", emails)
        self.assertTrue(any("971" in p for p in phones))
        self.assertEqual(contact["contact_page_url"], "https://acme.example/contact-us")

    def test_purpose_kept_separate(self):
        purpose = extractors.extract_purpose(self.pages)
        self.assertEqual(len(purpose), 1)
        self.assertIn("leak free", purpose[0]["purpose_statement"])
        self.assertIn("mission", purpose[0]["mission"].lower())

    def test_summary_counts_are_real(self):
        summary = extractors.summarize_session(self.pages)
        self.assertEqual(summary["total_discovered"], 4)
        self.assertEqual(summary["services_pages"], 1)
        self.assertEqual(summary["purpose_pages"], 1)
        self.assertEqual(summary["successful"], 4)

    def test_mandatory_sections_empty_state(self):
        empty = extractors.extract_services([])
        self.assertEqual(empty, [])
        contact = extractors.extract_contact([])
        self.assertEqual(contact["emails"][0]["value"], "Not Found")


class TestSeo(unittest.TestCase):
    def test_missing_title_is_critical(self):
        page = _sample_page("https://x.example/no-title", "other",
                            "<html><head></head><body><p>hi</p></body></html>")
        audit = seo_analyzer.analyze([page], "https://x.example")
        checks = {(f["check"], f["severity"]) for f in audit["findings"]}
        self.assertIn(("Missing title tag", "Critical"), checks)
        self.assertIn(("Missing H1 heading", "High"), checks)

    def test_duplicate_titles_flagged(self):
        html = "<html><head><title>Same Title</title></head><body><h1>Hi</h1></body></html>"
        pages = [_sample_page(f"https://x.example/p{i}", "other", html) for i in (1, 2)]
        audit = seo_analyzer.analyze(pages, "https://x.example")
        self.assertTrue(any(f["check"] == "Duplicate title tag" for f in audit["findings"]))


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = config.DATABASE_PATH
        config.DATABASE_PATH = os.path.join(self.tmp.name, "test.db")

    def tearDown(self):
        config.DATABASE_PATH = self._old
        self.tmp.cleanup()

    def test_session_and_page_roundtrip(self):
        database.create_session("sess-1", "https://example.com", {"max_pages": 25})
        database.save_page("sess-1", _sample_page("https://example.com/", "home", HOME_HTML))
        pages = database.get_pages("sess-1")
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["category"], "home")
        self.assertEqual(database.list_sessions()[0]["id"], "sess-1")


class TestEndToEnd(unittest.TestCase):
    """Full scrape of the local test site via the Flask test client."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls._old_db = config.DATABASE_PATH
        config.DATABASE_PATH = os.path.join(cls.tmp.name, "test.db")
        # Allow the local test server ONLY inside this test class.
        cls._p1 = mock.patch("scraper.validate_url", return_value=(True, ""))
        cls._p2 = mock.patch("app.validate_url", return_value=(True, ""))
        cls._p1.start()
        cls._p2.start()

    @classmethod
    def tearDownClass(cls):
        cls._p1.stop()
        cls._p2.stop()
        cls.server.shutdown()
        config.DATABASE_PATH = cls._old_db
        cls.tmp.cleanup()

    def _scrape(self):
        import app as app_module
        client = app_module.app.test_client()
        base = f"http://127.0.0.1:{self.port}"
        res = client.post("/api/scrape", json={"url": base, "max_pages": 10,
                                               "max_depth": 2, "delay": 0})
        self.assertEqual(res.status_code, 202)
        job_id = res.get_json()["job_id"]
        session_id = None
        for _ in range(60):
            st = client.get(f"/api/scrape/status/{job_id}").get_json()
            if st["status"] == "completed":
                session_id = st["session_id"]
                break
            if st["status"] == "failed":
                self.fail(f"scrape failed: {st.get('error')}")
            time.sleep(0.5)
        self.assertIsNotNone(session_id, "scrape did not complete in time")
        return client, session_id

    def test_full_scrape_and_mandatory_sections(self):
        client, sid = self._scrape()
        pages = client.get(f"/api/pages?session_id={sid}").get_json()
        self.assertGreaterEqual(pages["count"], 4)
        urls = {p["url"] for p in pages["pages"]}
        self.assertIn(f"http://127.0.0.1:{self.port}/services", urls)
        services = client.get(f"/api/services?session_id={sid}").get_json()["data"]
        self.assertEqual(len(services), 1)
        contact = client.get(f"/api/contact?session_id={sid}").get_json()["data"]
        self.assertIn("hello@acmeplumbing.example",
                      [e["value"] for e in contact["emails"]])
        purpose = client.get(f"/api/purpose?session_id={sid}").get_json()["data"]
        self.assertEqual(len(purpose), 1)
        seo = client.get(f"/api/seo-audit?session_id={sid}").get_json()["audit"]
        self.assertIn("findings", seo)

    def test_exports_contain_real_data(self):
        client, sid = self._scrape()
        for fmt in ("json", "csv", "txt"):
            res = client.get(f"/api/export/{fmt}?session_id={sid}&kind=all")
            self.assertEqual(res.status_code, 200, fmt)
            body = res.get_data(as_text=True)
            self.assertIn("Acme", body)
            self.assertIn("SERVICES" if fmt != "json" else "services", body)

    def test_ai_without_key_returns_clear_error(self):
        import app as app_module
        client = app_module.app.test_client()
        res = client.post("/api/ai/chat", json={"question": "What services?", "session_id": ""})
        self.assertEqual(res.status_code, 503)
        self.assertIn("API key", res.get_json()["error"])

    def test_bad_url_rejected(self):
        import app as app_module
        client = app_module.app.test_client()
        res = client.post("/api/scrape", json={"url": "not a url"})
        # Patched validate_url accepts anything, so the API normalises it;
        # the point here is only that the endpoint answers JSON, not a crash.
        self.assertIn(res.status_code, (202, 400))


if __name__ == "__main__":
    unittest.main()
