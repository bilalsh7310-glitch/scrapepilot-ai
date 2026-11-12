"""ScrapePilot AI — OpenRouter AI assistant (section 11/20/21).

The AI only ever sees the current session's extracted data (plus the
user-supplied portfolio profile when asked about it). It must not invent
results: the system prompt tells it to say when data is missing, and
extracted facts are labelled as facts, separate from summaries.
Scraping works fully without a key — AI is an optional layer.
"""
import json

import requests

import config


def _portfolio_text():
    p = config.PORTFOLIO_PROFILE
    return (
        f"Name: {p['name']}. Background: {p['background']}. "
        f"Skills: {', '.join(p['skills'])}. "
        f"Technical interests: {', '.join(p['technical_interests'])}. "
        f"Experience: {p['experience']}. "
        f"Projects: {', '.join(p['projects'])}. "
        f"Education: {p['education']}."
    )


def build_context(session, pages, summary, services, contact, purpose, seo):
    """A compact, factual context block for the model."""
    lines = [
        f"Scraped website: {session['url']}",
        f"Pages discovered: {summary['total_discovered']} "
        f"(successful: {summary['successful']}, failed: {summary['failed']})",
        f"Services pages: {summary['services_pages']}, "
        f"products: {summary['products_found']}, "
        f"purpose/about pages: {summary['purpose_pages']}.",
        "",
        "SERVICES (extracted facts):",
    ]
    for s in services[:15]:
        lines.append(f"- {s['service_name']} — {s['url']} — {s['description'][:160]}")
    if not services:
        lines.append("- No matching page discovered.")
    lines.append("")
    lines.append("CONTACT (extracted facts):")
    lines.append(f"Business name: {contact['business_name']}")
    lines.append("Emails: " + ", ".join(
        e["value"] for e in contact["emails"][:5]))
    lines.append("Phones: " + ", ".join(
        e["value"] for e in contact["phones"][:5]))
    lines.append("Contact page: " + str(contact["contact_page_url"]))
    lines.append("")
    lines.append("PURPOSE / ABOUT (extracted facts):")
    for p in purpose[:5]:
        lines.append(f"- {p['page_title']} — {p['url']} — "
                     f"{p['purpose_statement'][:200]}")
    if not purpose:
        lines.append("- No matching page discovered.")
    lines.append("")
    lines.append("SEO FINDINGS (top 10 by severity):")
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    for f in sorted(seo["findings"], key=lambda x: order.get(x["severity"], 9))[:10]:
        lines.append(f"- [{f['severity']}] {f['check']}: {f['url']} — {f['evidence'][:120]}")
    lines.append("")
    lines.append("ALL PAGE TITLES + URLS:")
    for p in pages[:40]:
        lines.append(f"- [{p.get('category')}] {p.get('title') or '(no title)'} — {p['url']}")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are the AI assistant inside ScrapePilot AI, a website scraping "
    "and data extraction tool. You answer ONLY from the extracted data "
    "given in the context. Rules: (1) Never invent services, prices, "
    "contact details, purpose statements or pages. If the data is missing, "
    "say so plainly — e.g. 'Not found in the scraped data'. "
    "(2) Keep extracted facts separate from your own summary or "
    "recommendations, and label which is which. "
    "(3) If asked about the portfolio profile (Bilal), use only the "
    "profile facts given; never invent employers, dates, qualifications "
    "or experience durations. (4) Be concise and practical."
)


def ask(question, context, portfolio_question=False):
    """Return (answer, error). error is '' on success."""
    if not config.OPENROUTER_API_KEY:
        return "", (
            "OpenRouter API key is not set. Copy .env.example to .env and "
            "add your free key from https://openrouter.ai/keys — scraping "
            "itself works without it; only the AI assistant needs it."
        )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if portfolio_question:
        messages.append({"role": "system",
                         "content": "Portfolio profile: " + _portfolio_text()})
    messages.append({"role": "system",
                     "content": "Extracted data from the current scraping "
                                "session:\n" + context})
    messages.append({"role": "user", "content": question})
    try:
        resp = requests.post(
            config.OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://127.0.0.1:5000",
                "X-Title": "ScrapePilot AI",
            },
            json={"model": config.OPENROUTER_MODEL, "messages": messages,
                  "temperature": 0.3, "max_tokens": 1200},
            timeout=60,
        )
    except requests.exceptions.RequestException as exc:
        return "", f"Could not reach OpenRouter: {exc}"
    if resp.status_code == 401:
        return "", "OpenRouter rejected the API key (401). Check OPENROUTER_API_KEY in .env."
    if resp.status_code == 429:
        return "", "OpenRouter rate limit reached (429). Wait a minute and try again."
    if resp.status_code != 200:
        return "", f"OpenRouter returned HTTP {resp.status_code}: {resp.text[:300]}"
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip(), ""
    except (KeyError, IndexError, ValueError):
        return "", "OpenRouter returned a response I could not read."
