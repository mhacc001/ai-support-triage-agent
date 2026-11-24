"""Triage one support request end to end.

Examples:
  python run.py sample_tickets/gpu_missing.txt            # Claude agent, asks before each write
  python run.py sample_tickets/gpu_missing.txt --auto-approve
  python run.py sample_tickets/gpu_missing.txt --offline  # scripted baseline, no API key
"""

import argparse
import threading
import time
from datetime import datetime
from pathlib import Path

from agent.approval import auto_approver, cli_approver
from agent.audit import AuditLog
from agent.tools import SupportAPI
from mock_services.api import create_app

PORT = 5055


def start_mock_api() -> str:
    app = create_app()
    thread = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=PORT, use_reloader=False), daemon=True)
    thread.start()
    time.sleep(0.8)
    return f"http://127.0.0.1:{PORT}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ticket_file", type=Path)
    parser.add_argument("--auto-approve", action="store_true", help="approve every write (demo only)")
    parser.add_argument("--offline", action="store_true", help="scripted baseline, no LLM")
    parser.add_argument("--api-url", help="use an already running support API instead of starting the mock")
    args = parser.parse_args()

    base_url = args.api_url or start_mock_api()
    api = SupportAPI(base_url)
    log = AuditLog(Path("logs") / f"run-{datetime.now():%Y%m%d-%H%M%S}.jsonl")
    approve = auto_approver if args.auto_approve else cli_approver
    request_text = args.ticket_file.read_text()

    if args.offline:
        from agent.offline import run_offline
        result = run_offline(request_text, api, approve, log)
    else:
        from agent.loop import run_agent
        result = run_agent(request_text, api, approve, log)

    print("\n--- RESULT ---")
    print(result)
    print(f"\nAudit log: {log.path}")


if __name__ == "__main__":
    main()
