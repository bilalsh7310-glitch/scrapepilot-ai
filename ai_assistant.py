
"""ScrapePilot AI, OpenRouter AI assistant."""

import requests
import config


SYSTEM_PROMPT = (
    "You are the AI assistant inside ScrapePilot AI, a website scraping "
    "and data extraction tool. You answer ONLY from the extracted data "
    "given in the context. Rules: "
    "(1) Never invent services, prices, contact details, purpose statements "
    "or pages. If data is missing, say so plainly. "
    "(2) Keep extracted facts separate from summaries or recommendations. "
    "(3) If asked about Bilal's portfolio, use only supplied profile facts. "
    "(4) Be concise and practical."
)


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


def build_context(session, pages, summary, services, contact,
                  purpose, seo):
    """Build a factual context block for the model."""

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
        lines.append(
            f"- {s['service_name']} — {s['url']} — "
            f"{s['description'][:160]}"
        )

    if not services:
        lines.append("- No matching page discovered.")

    lines.extend(["", "CONTACT (extracted facts):"])
    lines.append(f"Business name: {contact['business_name']}")
    lines.append("Emails: " + ", ".join(
        e["value"] for e in contact["emails"][:5]
    ))
    lines.append("Phones: " + ", ".join(
        e["value"] for e in contact["phones"][:5]
    ))
    lines.append("Contact page: " + str(contact["contact_page_url"]))

    lines.extend(["", "PURPOSE / ABOUT (extracted facts):"])

    for p in purpose[:5]:
        lines.append(
            f"- {p['page_title']} — {p['url']} — "
            f"{p['purpose_statement'][:200]}"
        )

    if not purpose:
        lines.append("- No matching page discovered.")

    lines.extend(["", "SEO FINDINGS (top 10 by severity):"])

    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

    for f in sorted(
        seo["findings"],
        key=lambda x: order.get(x["severity"], 9)
    )[:10]:
        lines.append(
            f"- [{f['severity']}] {f['check']}: "
            f"{f['url']} — {f['evidence'][:120]}"
        )

    lines.extend(["", "ALL PAGE TITLES + URLS:"])

    for p in pages[:40]:
        lines.append(
            f"- [{p.get('category')}] "
            f"{p.get('title') or '(no title)'} — {p['url']}"
        )

    return "\n".join(lines)


def ask(question, context, portfolio_question=False):
    """Return (answer, error)."""

    if not config.OPENROUTER_API_KEY:
        return "", (
            "OpenRouter API key is not set. Add OPENROUTER_API_KEY "
            "to your .env file."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    if portfolio_question:
        messages.append({
            "role": "system",
            "content": "Portfolio profile: " + _portfolio_text()
        })

    messages.append({
        "role": "system",
        "content": (
            "Extracted data from the current scraping session:\n"
            + context
        )
    })

    messages.append({
        "role": "user",
        "content": question
    })

    # Try the configured model first, then fallback models.
    models = [
        config.OPENROUTER_MODEL,
        "openrouter/free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemma-3-27b-it:free",
    ]

    # Remove duplicate model names while keeping their order.
    models = list(dict.fromkeys(models))

    last_error = ""

    for model in models:
        try:
            resp = requests.post(
                config.OPENROUTER_URL,
                headers={
                    "Authorization": (
                        f"Bearer {config.OPENROUTER_API_KEY}"
                    ),
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://scrapepilot-ai.onrender.com",
                    "X-Title": "ScrapePilot AI",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 1200,
                },
                timeout=60,
            )

        except requests.exceptions.RequestException as exc:
            last_error = f"Connection error: {exc}"
            continue

        if resp.status_code == 200:
            try:
                data = resp.json()
                answer = data["choices"][0]["message"]["content"]

                if answer:
                    return answer.strip(), ""

                last_error = "Model returned an empty answer."

            except (KeyError, IndexError, ValueError):
                last_error = "OpenRouter returned an unreadable response."

        elif resp.status_code == 401:
            return "", (
                "OpenRouter rejected your API key (401). "
                "Check OPENROUTER_API_KEY."
            )

        elif resp.status_code in (402, 404, 429) or resp.status_code >= 500:
            last_error = (
                f"Model {model} returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
            continue

        else:
            return "", (
                f"OpenRouter returned HTTP {resp.status_code}: "
                f"{resp.text[:300]}"
            )

    return "", (
        "All available models failed. Last error: " + last_error
    )
