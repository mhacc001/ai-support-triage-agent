"""Tool definitions the agent can call, and the code that runs them.

Read tools (search_knowledge_base, check_part_availability, get_ticket) run
straight away. Write tools (create_ticket, update_ticket) change the ticketing
system, so they go through the human approval gate first.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

WRITE_TOOLS = {"create_ticket", "update_ticket"}

SEVERITIES = ["sev1-critical", "sev2-high", "sev3-medium", "sev4-low"]
QUEUES = ["field-dispatch", "remote-support", "engineering-escalation"]

TOOLS = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Search the AI-server support knowledge base for troubleshooting articles. "
            "Use plain keywords from the customer's symptoms (for example 'gpu not detected'). "
            "Returns up to 3 articles with symptoms, steps and the part to replace if the steps fail."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keywords describing the symptom."}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_part_availability",
        "description": (
            "Check stock, depot and lead time for a replacement part by SKU. "
            "Use the SKU from a knowledge base article's part_on_failure field."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"sku": {"type": "string", "description": "Part SKU, e.g. GPU-H100-SXM5-80G."}},
            "required": ["sku"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_ticket",
        "description": "Read an existing support ticket by its ID (format TKT-####).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_ticket",
        "description": (
            "Open a new support ticket. A human must approve this before it runs. "
            "Include the KB article you matched and the recommended next step in the summary."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short ticket title."},
                "severity": {"type": "string", "enum": SEVERITIES},
                "assigned_queue": {"type": "string", "enum": QUEUES},
                "summary": {"type": "string", "description": "Diagnosis, KB article ID and recommended next step."},
                "customer": {"type": "string", "description": "Customer or account name from the request."},
            },
            "required": ["title", "severity", "assigned_queue", "summary", "customer"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_ticket",
        "description": (
            "Add a note to an existing ticket and optionally change its status or queue, "
            "or record a part to dispatch. A human must approve this before it runs."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "note": {"type": "string"},
                "status": {"type": "string", "enum": ["open", "pending-customer", "pending-part", "resolved"]},
                "assigned_queue": {"type": "string", "enum": QUEUES},
                "dispatch_part": {"type": "string", "description": "SKU to dispatch, if a part is needed."},
            },
            "required": ["ticket_id", "note"],
            "additionalProperties": False,
        },
    },
]


class SupportAPI:
    """Thin HTTP client for the mock back-end (stdlib only)."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise ToolError(f"{method} {path} failed with HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise ToolError(f"could not reach the support API at {self.base_url}: {e.reason}") from e

    def search_kb(self, query):
        return self._call("GET", "/kb/search?" + urllib.parse.urlencode({"q": query}))

    def part(self, sku):
        return self._call("GET", "/parts/" + urllib.parse.quote(sku))

    def get_ticket(self, tid):
        return self._call("GET", "/tickets/" + urllib.parse.quote(tid))

    def create_ticket(self, fields):
        return self._call("POST", "/tickets", fields)

    def update_ticket(self, tid, fields):
        return self._call("PATCH", "/tickets/" + urllib.parse.quote(tid), fields)


class ToolError(Exception):
    pass


def validate(name: str, args: dict) -> None:
    """Check the input against the tool's schema before anything runs."""
    spec = next((t for t in TOOLS if t["name"] == name), None)
    if spec is None:
        raise ToolError(f"unknown tool {name}")
    schema = spec["input_schema"]
    extra = set(args) - set(schema["properties"])
    missing = [k for k in schema["required"] if k not in args]
    if extra or missing:
        raise ToolError(f"invalid input for {name}: missing={missing} unexpected={sorted(extra)}")
    for key, value in args.items():
        prop = schema["properties"][key]
        if not isinstance(value, str):
            raise ToolError(f"{name}.{key} must be a string")
        if "enum" in prop and value not in prop["enum"]:
            raise ToolError(f"{name}.{key} must be one of {prop['enum']}")


def run_tool(name: str, args: dict, api: SupportAPI, approve: Callable[[str, dict], tuple[bool, str]], log) -> tuple[str, bool]:
    """Run one tool call. Returns (result_text, is_error)."""
    try:
        validate(name, args)
        if name in WRITE_TOOLS:
            approved, reason = approve(name, args)
            log.event("approval", tool=name, input=args, approved=approved, reason=reason)
            if not approved:
                return (f"The human reviewer declined this action. Reason: {reason or 'none given'}. "
                        "Do not retry the same action; explain what you would recommend instead."), False
        if name == "search_knowledge_base":
            result = api.search_kb(args["query"])
        elif name == "check_part_availability":
            result = api.part(args["sku"])
        elif name == "get_ticket":
            result = api.get_ticket(args["ticket_id"])
        elif name == "create_ticket":
            result = api.create_ticket(args)
        elif name == "update_ticket":
            tid = args["ticket_id"]
            result = api.update_ticket(tid, {k: v for k, v in args.items() if k != "ticket_id"})
        else:
            raise ToolError(f"unknown tool {name}")
        log.event("tool_result", tool=name, input=args, ok=True)
        return json.dumps(result), False
    except ToolError as e:
        log.event("tool_result", tool=name, input=args, ok=False, error=str(e))
        return f"Error: {e}", True
