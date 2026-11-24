# AI Support Triage Agent

An agentic AI workflow that triages AI-server support requests end to end: it reads the customer's message, searches a knowledge base, checks replacement-part availability, opens a ticket in the right queue, and books a part dispatch. **Every action that changes the ticketing system waits for human approval**, and every step is written to an audit log.

Built with Python, the Claude API (tool use), and a small REST back-end that stands in for the systems a support team integrates with.

```
customer request
      │
      ▼
 Claude (claude-opus-5-5) ── decides the next step
      │  tool calls
      ▼
 ┌────────────────────────────────────────────────────────────┐
 │ search_knowledge_base   check_part_availability   get_ticket │  read: run immediately
 │ create_ticket           update_ticket                      │  write: human approval first
 └────────────────────────────────────────────────────────────┘
      │  HTTP
      ▼
 mock support API (Flask): /kb/search  /parts/<sku>  /tickets
      │
      ▼
 logs/run-*.jsonl  (every model turn, tool call, approval decision)
```

## What it shows

- **Agentic loop**: Claude chooses which tool to call and when; the loop feeds each result back until the ticket is triaged.
- **System integration over REST**: knowledge base search, parts inventory lookup, ticket create/update.
- **Guardrails**:
  - write actions go through a human approval gate, and a declined action is never sent to the API
  - strict JSON schemas on every tool, plus server-side validation of each input before it runs
  - a turn limit
  - handling for API errors, refusals (with server-side model fallback) and `max_tokens`
- **Auditability**: JSON Lines log of each model turn (with token usage), tool call and approval.
- **Tests**: 5 pytest tests, including a fake Claude client that proves a declined `create_ticket` never reaches the ticketing API.
- **Offline baseline**: a scripted, no-LLM mode that runs the same tools and gate. This way the project runs and the tests pass without an API key, and you can compare the agent against fixed rules.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# scripted baseline, no API key needed
python run.py sample_tickets/gpu_missing.txt --offline --auto-approve

# the Claude agent (needs ANTHROPIC_API_KEY or `ant auth login`)
python run.py sample_tickets/gpu_missing.txt                 # asks you before each write
python run.py sample_tickets/psu_redundancy.txt --auto-approve

pytest -q
```

The mock API starts automatically on `127.0.0.1:5055`. Point the agent at another service with `--api-url`.

## Sample scenarios

| File | Expected outcome |
|---|---|
| `gpu_missing.txt` | KB-1001, GPU module in stock in Austin, field dispatch, part booked |
| `psu_redundancy.txt` | KB-1003, hot-swap PSU, field dispatch |
| `bmc_unreachable.txt` | KB-1005, no part needed, remote support |

## Example offline run

```
[auto-approve] create_ticket: {"title": "GPU not detected after install or reboot", "severity": "sev2-high", "assigned_queue": "field-dispatch", ...}
[auto-approve] update_ticket: {"ticket_id": "TKT-5001", "note": "Dispatch GPU-H100-SXM5-80G from Austin.", "status": "pending-part", ...}

--- RESULT ---
TKT-5001 | sev2-high | field-dispatch | Matched KB-1001 (GPU not detected after install or reboot). ... Part GPU-H100-SXM5-80G: 12 in stock at Austin, 1 day lead time.
```

## Project layout

```
agent/loop.py       Claude agent loop (Messages API, tool use, error handling)
agent/tools.py      tool schemas, input validation, HTTP client, approval gate
agent/approval.py   interactive / auto / deny approvers
agent/audit.py      JSON Lines audit log
agent/offline.py    scripted no-LLM baseline
mock_services/      Flask mock of the knowledge base, parts inventory and ticketing
sample_tickets/     example customer requests
tests/              pytest suite (fake Claude client, no network)
```

## Notes and next steps

- The knowledge base, parts and tickets are fictional demo data.
- Next: a Salesforce or ServiceNow adapter behind the same `SupportAPI` interface, a small eval set comparing the agent against the offline baseline, and a web approval queue in place of the CLI prompt.
