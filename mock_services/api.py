"""Mock support back-end: knowledge base, parts inventory and ticketing.

Stands in for the systems a real support team integrates with (a knowledge
base, a parts/repair system, a ticketing tool like Salesforce Service Cloud).
Everything is in memory so the demo resets on every start.

Run on its own:  python -m mock_services.api   (listens on 127.0.0.1:5055)
"""

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, request

DATA = Path(__file__).parent / "data"


def create_app() -> Flask:
    app = Flask(__name__)
    kb = json.loads((DATA / "kb.json").read_text())
    parts = json.loads((DATA / "parts.json").read_text())
    tickets: dict[str, dict] = {}
    ids = itertools.count(5001)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/kb/search")
    def kb_search():
        q = request.args.get("q", "").lower().strip()
        if not q:
            abort(400, "query parameter q is required")
        words = [w for w in q.split() if len(w) > 2]
        scored = []
        for art in kb:
            text = " ".join([art["title"], art["symptoms"], " ".join(art["tags"])]).lower()
            score = sum(1 for w in words if w in text)
            if score:
                scored.append((score, art))
        scored.sort(key=lambda s: -s[0])
        return jsonify([a for _, a in scored[:3]])

    @app.get("/parts/<sku>")
    def part(sku):
        if sku not in parts:
            abort(404, f"unknown part {sku}")
        return jsonify({"sku": sku, **parts[sku]})

    @app.post("/tickets")
    def create_ticket():
        body = request.get_json(force=True)
        for field in ("title", "severity", "summary"):
            if not body.get(field):
                abort(400, f"{field} is required")
        tid = f"TKT-{next(ids)}"
        now = datetime.now(timezone.utc).isoformat()
        tickets[tid] = {"id": tid, "status": "open", "created_at": now, "notes": [], **body}
        return jsonify(tickets[tid]), 201

    @app.get("/tickets/<tid>")
    def get_ticket(tid):
        if tid not in tickets:
            abort(404, f"unknown ticket {tid}")
        return jsonify(tickets[tid])

    @app.patch("/tickets/<tid>")
    def update_ticket(tid):
        if tid not in tickets:
            abort(404, f"unknown ticket {tid}")
        body = request.get_json(force=True)
        t = tickets[tid]
        if body.get("note"):
            t["notes"].append({"at": datetime.now(timezone.utc).isoformat(), "text": body["note"]})
        for field in ("status", "severity", "assigned_queue", "dispatch_part"):
            if body.get(field):
                t[field] = body[field]
        return jsonify(t)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5055)
