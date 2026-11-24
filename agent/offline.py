"""Scripted offline mode: no LLM, fixed steps.

Runs the same tools, approval gate and audit log as the Claude agent, but the
"decisions" are simple keyword rules. It exists so the project can be run and
tested without an API key. It is a baseline, not the agent.
"""

import json

from .tools import run_tool


def run_offline(request_text: str, api, approve, log) -> str:
    log.event("start", model="offline-scripted", request=request_text)
    text = request_text.lower()

    kb_text, _ = run_tool("search_knowledge_base", {"query": request_text[:200]}, api, approve, log)
    articles = json.loads(kb_text) if kb_text.startswith("[") else []
    article = articles[0] if articles else None

    down = any(w in text for w in ("down", "outage", "cannot train", "production stopped"))
    severity = "sev1-critical" if down else "sev2-high" if article else "sev3-medium"

    part_line, part = "", None
    if article and article.get("part_on_failure"):
        part_text, err = run_tool("check_part_availability", {"sku": article["part_on_failure"]}, api, approve, log)
        if not err:
            part = json.loads(part_text)
            part_line = f" Part {part['sku']}: {part['in_stock']} in stock at {part['depot']}, {part['lead_time_days']} day lead time."

    queue = "engineering-escalation" if not article else "field-dispatch" if part else "remote-support"
    summary = (f"Matched {article['id']} ({article['title']}). Next step: {article['steps'][0]}{part_line}"
               if article else "No KB match; needs engineering review.")
    created_text, err = run_tool("create_ticket", {
        "title": (article["title"] if article else "Unclassified AI server issue")[:80],
        "severity": severity,
        "assigned_queue": queue,
        "summary": summary,
        "customer": "see request",
    }, api, approve, log)
    if err or not created_text.startswith("{"):
        log.event("finish", summary=created_text)
        return f"Ticket not created: {created_text}"
    ticket = json.loads(created_text)

    if part and part["in_stock"] > 0:
        run_tool("update_ticket", {"ticket_id": ticket["id"], "note": f"Dispatch {part['sku']} from {part['depot']}.",
                                   "status": "pending-part", "dispatch_part": part["sku"]}, api, approve, log)

    result = f"{ticket['id']} | {severity} | {queue} | {summary}"
    log.event("finish", summary=result)
    return result
