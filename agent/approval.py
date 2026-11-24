"""Human-in-the-loop approval for write actions."""

import json


def cli_approver(name: str, args: dict) -> tuple[bool, str]:
    """Show the proposed write and ask the operator to approve it."""
    print("\n" + "=" * 60)
    print(f"APPROVAL NEEDED: the agent wants to run {name}")
    print(json.dumps(args, indent=2))
    print("=" * 60)
    answer = input("Approve? [y]es / [n]o: ").strip().lower()
    if answer.startswith("y"):
        return True, "approved by operator"
    reason = input("Reason for declining (optional): ").strip()
    return False, reason


def auto_approver(name: str, args: dict) -> tuple[bool, str]:
    """For demos and tests only: approve every write and say so in the log."""
    print(f"[auto-approve] {name}: {json.dumps(args)}")
    return True, "auto-approved (demo mode)"


def deny_approver(name: str, args: dict) -> tuple[bool, str]:
    """For tests: decline every write."""
    return False, "declined in test"
