
"""
ScrapePilot AI
Flask application configured for Render deployment.

Features:
    Website crawling in a background thread
    Real time scraping progress
    Website data extraction
    SEO audit
    AI chat
    Scraping history
    CSV, JSON and TXT exports
    Health check endpoint
"""

import csv
import json
import os
import re
import threading
import uuid

from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_file, send_from_directory

import ai_assistant
import config
import crawler
import database
import extractors
import seo_analyzer

from scraper import validate_url


# ---------------------------------------------------------
# Flask configuration
# ---------------------------------------------------------

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)

app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

# Render provides PORT automatically.
PORT = int(os.environ.get("PORT", config.PORT))

# Background jobs are stored in memory.
# Keep one Gunicorn worker when using this job storage.
JOBS = {}

JOBS_LOCK = threading.Lock()


# ---------------------------------------------------------
# Database initialization
# ---------------------------------------------------------

def initialize_database():
    """
    Initialize the database when the application loads.

    Gunicorn imports app.py instead of executing it directly.
    Therefore database initialization must not be limited
    to the __main__ block.
    """
    database.init_db()


initialize_database()


# ---------------------------------------------------------
# Health check
# ---------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "application": "ScrapePilot AI",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


# ---------------------------------------------------------
# Scraping settings
# ---------------------------------------------------------

def _clamp_settings(body):

    def _int(name, default, cap):
        try:
            value = int(body.get(name, default))
            return max(1, min(value, cap))
        except (TypeError, ValueError):
            return default

    def _float(name, default, minimum, maximum):
        try:
            value = float(body.get(name, default))

            if value != value:
                return default

            return max(minimum, min(value, maximum))

        except (TypeError, ValueError):
            return default

    return {
        "max_pages": _int(
            "max_pages",
            config.DEFAULT_MAX_PAGES,
            config.MAX_PAGES_CAP
        ),

        "max_depth": _int(
            "max_depth",
            config.DEFAULT_MAX_DEPTH,
            config.MAX_DEPTH_CAP
        ),

        "timeout": _float(
            "timeout",
            config.DEFAULT_TIMEOUT,
            5,
            config.MAX_TIMEOUT_CAP
        ),

        "delay": _float(
            "delay",
            config.DEFAULT_DELAY,
            config.MIN_DELAY,
            config.MAX_DELAY
        ),

        "scrape_all": bool(body.get("scrape_all", True)),

        "include_patterns": [
            p for p in (body.get("include_patterns") or [])
            if isinstance(p, str)
        ][:20],

        "exclude_patterns": [
            p for p in (body.get("exclude_patterns") or [])
            if isinstance(p, str)
        ][:20],

        "js_rendering": bool(body.get("js_rendering", False))
    }


# ---------------------------------------------------------
# Background crawler
# ---------------------------------------------------------

def _run_crawl(job_id, url, settings):

    session_id = str(uuid.uuid4())

    try:

        with JOBS_LOCK:
            JOBS[job_id].update({
                "session_id": session_id,
                "status": "running"
            })

        database.create_session(
            session_id,
            url,
            settings
        )

        state = {
            "phase": "starting",
            "done": 0,
            "queued": 0,
            "max_pages": settings["max_pages"],
            "current_url": url
        }

        def progress(p):

            state.update(p)

            with JOBS_LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["progress"] = dict(state)

        pages, stats = crawler.crawl(
            url,
            settings,
            progress=progress
        )

        for page in pages:
            database.save_page(session_id, page)

        database.update_session(
            session_id,
            status="completed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            discovered_count=stats["discovered"],
            success_count=stats["successful"],
            failed_count=stats["failed"]
        )

        with JOBS_LOCK:
            JOBS[job_id].update({
                "status": "completed",
                "stats": stats,
                "progress": {
                    "phase": "done",
                    "done": stats["discovered"],
                    "max_pages": settings["max_pages"]
                }
            })

    except Exception as exc:

        error_message = str(exc)

        try:
            if session_id:
                database.update_session(
                    session_id,
                    status="failed",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    error=error_message
                )
        except Exception:
            pass

        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id].update({
                    "status": "failed",
                    "error": error_message
                })


# ---------------------------------------------------------
# Session helper
# ---------------------------------------------------------

def _session_or_404(session_id):

    session = database.get_session(session_id) if session_id else None

    if not session:
        return None, (
            jsonify({
                "error": "Session not found. Run a scrape first."
            }),
            404
        )

    return session, None


# ---------------------------------------------------------
# Website data bundle
# ---------------------------------------------------------

def _bundle(session_id):

    pages = database.get_pages(session_id)

    summary = extractors.summarize_session(pages)

    return {
        "pages": pages,
        "summary": summary,
        "services": extractors.extract_services(pages),
        "products": extractors.extract_products(pages),
        "contact": extractors.extract_contact(pages),
        "purpose": extractors.extract_purpose(pages),
        "company": extractors.extract_company(pages),
        "blogs": extractors.extract_blogs(pages)
    }


# ---------------------------------------------------------
# Main pages
# ---------------------------------------------------------

@app.route("/")
def index():

    return send_from_directory(
        app.template_folder,
        "index.html"
    )


@app.route("/api/config")
def api_config():

    return jsonify({

        "api_key_configured": bool(config.OPENROUTER_API_KEY),

        "model": config.OPENROUTER_MODEL,

        "defaults": {
            "max_pages": config.DEFAULT_MAX_PAGES,
            "max_depth": config.DEFAULT_MAX_DEPTH,
            "timeout": config.DEFAULT_TIMEOUT,
            "delay": config.DEFAULT_DELAY
        },

        "caps": {
            "max_pages": config.MAX_PAGES_CAP,
            "max_depth": config.MAX_DEPTH_CAP
        },

        "js_rendering_available": False,

        "js_rendering_note": (
            "Playwright is not installed in this build. "
            "JavaScript-rendered pages fall back to plain HTML fetching."
        )

    })


# ---------------------------------------------------------
# Start scraping
# ---------------------------------------------------------

@app.route("/api/scrape", methods=["POST"])
def api_scrape():

    body = request.get_json(silent=True) or {}

    url = (body.get("url") or "").strip()

    if not url:
        return jsonify({
            "error": "Enter a website URL first."
        }), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    ok, err = validate_url(url)

    if not ok:
        return jsonify({
            "error": f"That URL cannot be scraped: {err}"
        }), 400

    settings = _clamp_settings(body)

    if settings["js_rendering"]:
        settings["js_rendering_note"] = (
            "Playwright is not installed, so pages were fetched as plain HTML."
        )

    job_id = str(uuid.uuid4())

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "starting",
            "progress": {},
            "session_id": None,
            "error": ""
        }

    thread = threading.Thread(
        target=_run_crawl,
        args=(job_id, url, settings),
        daemon=True
    )

    thread.start()

    return jsonify({
        "job_id": job_id,
        "status": "started"
    }), 202


# ---------------------------------------------------------
# Scraping progress
# ---------------------------------------------------------

@app.route("/api/scrape/status/<job_id>", methods=["GET"])
def api_status(job_id):

    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if not job:
            return jsonify({
                "error": "Unknown job id."
            }), 404

        return jsonify(dict(job))


# ---------------------------------------------------------
# Data routes
# ---------------------------------------------------------

def _data_route(kind):

    session_id = request.args.get("session_id", "")

    session, err = _session_or_404(session_id)

    if err:
        return err

    bundle = _bundle(session_id)

    return jsonify({
        "session": session,
        "summary": bundle["summary"],
        "data": bundle[kind]
    })


@app.route("/api/pages", methods=["GET"])
def api_pages():

    session_id = request.args.get("session_id", "")

    session, err = _session_or_404(session_id)

    if err:
        return err

    bundle = _bundle(session_id)

    category = request.args.get("category", "")

    query = (
        request.args.get("q", "") or ""
    ).lower()

    pages = bundle["pages"]

    if category:
        pages = [
            p for p in pages
            if (p.get("category") or "") == category
        ]

    if query:
        pages = [
            p for p in pages
            if query in (p.get("title") or "").lower()
            or query in p["url"].lower()
        ]

    return jsonify({
        "session": session,
        "summary": bundle["summary"],
        "pages": pages,
        "count": len(pages)
    })


@app.route("/api/services")
def api_services():
    return _data_route("services")


@app.route("/api/products")
def api_products():
    return _data_route("products")


@app.route("/api/contact")
def api_contact():
    return _data_route("contact")


@app.route("/api/purpose")
def api_purpose():
    return _data_route("purpose")


@app.route("/api/company")
def api_company():
    return _data_route("company")


@app.route("/api/blogs")
def api_blogs():
    return _data_route("blogs")


# ---------------------------------------------------------
# SEO audit
# ---------------------------------------------------------

@app.route("/api/seo-audit")
def api_seo():

    session_id = request.args.get("session_id", "")

    session, err = _session_or_404(session_id)

    if err:
        return err

    bundle = _bundle(session_id)

    audit = seo_analyzer.analyze(
        bundle["pages"],
        session["url"]
    )

    return jsonify({
        "session": session,
        "summary": bundle["summary"],
        "audit": audit
    })


# ---------------------------------------------------------
# Page category update
# ---------------------------------------------------------

@app.route("/api/pages/<int:page_id>/category", methods=["POST"])
def api_recategorize(page_id):

    body = request.get_json(silent=True) or {}

    category = (body.get("category") or "").strip()

    from page_discovery import CATEGORY_LABELS

    if category not in CATEGORY_LABELS:
        return jsonify({
            "error": "Unknown category."
        }), 400

    if database.update_page_category(page_id, category) == 0:
        return jsonify({
            "error": "Page not found."
        }), 404

    return jsonify({
        "ok": True,
        "category": category
    })


# ---------------------------------------------------------
# Delete page
# ---------------------------------------------------------

@app.route("/api/pages/<int:page_id>", methods=["DELETE"])
def api_delete_page(page_id):

    if database.delete_page(page_id) == 0:
        return jsonify({
            "error": "Page not found."
        }), 404

    return jsonify({
        "ok": True
    })


# ---------------------------------------------------------
# AI assistant
# ---------------------------------------------------------

@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():

    body = request.get_json(silent=True) or {}

    question = (body.get("question") or "").strip()

    session_id = body.get("session_id", "")

    if not question:
        return jsonify({
            "error": "Ask a question first."
        }), 400

    portfolio_q = any(
        word in question.lower()
        for word in (
            "bilal",
            "portfolio",
            "your experience",
            "your skills"
        )
    )

    context = ""

    if session_id:

        session, err = _session_or_404(session_id)

        if err:
            return err

        bundle = _bundle(session_id)

        audit = seo_analyzer.analyze(
            bundle["pages"],
            session["url"]
        )

        context = ai_assistant.build_context(
            session,
            bundle["pages"],
            bundle["summary"],
            bundle["services"],
            bundle["contact"],
            bundle["purpose"],
            audit
        )

    answer, error = ai_assistant.ask(
        question,
        context,
        portfolio_q
    )

    if error:
        return jsonify({
            "error": error
        }), 503

    return jsonify({
        "answer": answer
    })


# ---------------------------------------------------------
# Scraping history
# ---------------------------------------------------------

@app.route("/api/history")
def api_history():

    return jsonify({
        "sessions": database.list_sessions()
    })


@app.route("/api/history/<session_id>")
def api_history_one(session_id):

    session, err = _session_or_404(session_id)

    if err:
        return err

    bundle = _bundle(session_id)

    return jsonify({
        "session": session,
        "summary": bundle["summary"],
        "pages": bundle["pages"]
    })


# ---------------------------------------------------------
# Export filename helper
# ---------------------------------------------------------

def _safe_filename(name):

    name = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        name
    )

    return name[:80] or "export"


# ---------------------------------------------------------
# Export reports
# ---------------------------------------------------------

@app.route("/api/export/<fmt>")
def api_export(fmt):

    if fmt not in ("csv", "json", "txt"):
        return jsonify({
            "error": "Format must be csv, json or txt."
        }), 400

    session_id = request.args.get("session_id", "")

    kind = request.args.get("kind", "all")

    session, err = _session_or_404(session_id)

    if err:
        return err

    bundle = _bundle(session_id)

    audit = seo_analyzer.analyze(
        bundle["pages"],
        session["url"]
    )

    stamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d-%H%M%S"
    )

    host = re.sub(
        r"[^A-Za-z0-9.-]",
        "_",
        session["url"].split("//")[-1].split("/")[0]
    )

    filename = _safe_filename(
        f"scrapepilot-{host}-{kind}-{stamp}.{fmt}"
    )

    os.makedirs(
        config.EXPORTS_DIR,
        exist_ok=True
    )

    if kind == "services":

        data = {
            "services": bundle["services"]
        }

    elif kind == "contact":

        data = {
            "contact": bundle["contact"]
        }

    elif kind == "purpose":

        data = {
            "purpose_about_pages": bundle["purpose"]
        }

    elif kind == "products":

        data = {
            "products": bundle["products"]
        }

    elif kind == "company":

        data = {
            "company": bundle["company"]
        }

    elif kind == "blogs":

        data = {
            "blog_articles": bundle["blogs"]
        }

    elif kind == "seo":

        data = {
            "seo_audit": audit
        }

    elif kind == "urls":

        data = {
            "urls": [
                p["url"] for p in bundle["pages"]
            ]
        }

    else:

        data = {
            "session": session,
            "summary": bundle["summary"],
            "services": bundle["services"],
            "products": bundle["products"],
            "contact": bundle["contact"],
            "purpose_about_pages": bundle["purpose"],
            "company": bundle["company"],
            "blog_articles": bundle["blogs"],
            "pages": [
                {
                    k: v for k, v in p.items()
                    if k != "data"
                }
                for p in bundle["pages"]
            ],
            "seo_audit": audit
        }

    path = os.path.join(
        config.EXPORTS_DIR,
        filename
    )

    if fmt == "json":

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=2,
                ensure_ascii=False
            )

        mimetype = "application/json"

    elif fmt == "csv":

        with open(
            path,
            "w",
            encoding="utf-8",
            newline=""
        ) as f:

            writer = csv.writer(f)

            if kind in ("services", "all"):

                writer.writerow(["SERVICES"])

                writer.writerow([
                    "service_name",
                    "url",
                    "category",
                    "description"
                ])

                for service in bundle["services"]:

                    writer.writerow([
                        service["service_name"],
                        service["url"],
                        service["category"],
                        service["description"]
                    ])

                writer.writerow([])

            writer.writerow(["PAGES"])

            writer.writerow([
                "url",
                "title",
                "category",
                "status_code",
                "scrape_status"
            ])

            for page in bundle["pages"]:

                writer.writerow([
                    page["url"],
                    page.get("title") or "",
                    page.get("category") or "",
                    page.get("status_code") or "",
                    page.get("scrape_status")
                ])

            writer.writerow([])

            writer.writerow(["CONTACT"])

            writer.writerow([
                "field",
                "value",
                "source_url"
            ])

            for email in bundle["contact"]["emails"]:

                writer.writerow([
                    "email",
                    email["value"],
                    email["source_url"]
                ])

            for phone in bundle["contact"]["phones"]:

                writer.writerow([
                    "phone",
                    phone["value"],
                    phone["source_url"]
                ])

        mimetype = "text/csv"

    else:

        lines = [
            "SCRAPEPILOT AI WEBSITE REPORT",
            f"Website: {session['url']}",
            f"Scraped: {session['started_at']}",
            (
                f"Pages: {bundle['summary']['total_discovered']} "
                f"(successful {bundle['summary']['successful']}, "
                f"failed {bundle['summary']['failed']})"
            ),
            ""
        ]

        lines.append("== SERVICES PAGES ==")

        if bundle["services"]:

            for service in bundle["services"]:

                lines.append(
                    f"{service['service_name']} | {service['url']}"
                )

        else:

            lines.append("No matching page discovered.")

        lines.append("")

        lines.append("== CONTACT INFORMATION ==")

        contact = bundle["contact"]

        lines.append(
            f"Business name: {contact['business_name']}"
        )

        lines.append(
            "Emails: " + ", ".join(
                email["value"]
                for email in contact["emails"]
            )
        )

        lines.append(
            "Phones: " + ", ".join(
                phone["value"]
                for phone in contact["phones"]
            )
        )

        lines.append(
            f"Contact page: {contact['contact_page_url']}"
        )

        lines.append("")

        lines.append("== PURPOSE / ABOUT PAGES ==")

        if bundle["purpose"]:

            for page in bundle["purpose"]:

                lines.append(
                    f"{page['page_title']} | {page['url']}"
                )

        else:

            lines.append("No matching page discovered.")

        lines.append("")

        lines.append("== SEO ANALYSIS ==")

        for finding in audit["findings"]:

            lines.append(
                f"[{finding['severity']}] "
                f"{finding['check']}: "
                f"{finding['url']} | "
                f"{finding['evidence']}"
            )

        if not audit["findings"]:

            lines.append("No issues found.")

        lines.append("")

        lines.append("== ALL DISCOVERED PAGES ==")

        for page in bundle["pages"]:

            lines.append(
                f"[{page.get('category')}] "
                f"{page['url']} "
                f"(HTTP {page.get('status_code')}, "
                f"{page.get('scrape_status')})"
            )

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as f:

            f.write("\n".join(lines))

        mimetype = "text/plain"

    database.record_export(
        session_id,
        fmt,
        kind,
        filename
    )

    return send_file(
        path,
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename
    )


# ---------------------------------------------------------
# Error handlers
# ---------------------------------------------------------

@app.errorhandler(404)
def not_found(_e):

    return jsonify({
        "error": "Not found."
    }), 404


@app.errorhandler(413)
def too_large(_e):

    return jsonify({
        "error": "Request too large."
    }), 413


@app.errorhandler(500)
def internal_error(_e):

    return jsonify({
        "error": "An internal server error occurred."
    }), 500


# ---------------------------------------------------------
# Local development
# ---------------------------------------------------------

if __name__ == "__main__":

    print(
        f"ScrapePilot AI running at http://{config.HOST}:{PORT}"
    )

    print(
        "OpenRouter key configured:",
        bool(config.OPENROUTER_API_KEY)
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=config.DEBUG,
        threaded=True
    )
