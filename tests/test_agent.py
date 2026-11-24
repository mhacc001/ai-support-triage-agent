import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.approval import auto_approver, deny_approver
from agent.audit import AuditLog
from agent.loop import run_agent
from agent.offline import run_offline
from agent.tools import SupportAPI, ToolError, run_tool, validate
from mock_services.api import create_app

PORT = 5099


@pytest.fixture(scope="module")
def api():
    app = create_app()
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=PORT, use_reloader=False), daemon=True).start()
    time.sleep(0.8)
    return SupportAPI(f"http://127.0.0.1:{PORT}")


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def test_validate_rejects_bad_enum_and_extra_fields():
    with pytest.raises(ToolError):
        validate("create_ticket", {"title": "x", "severity": "urgent!!", "assigned_queue": "remote-support",
                                   "summary": "s", "customer": "c"})
    with pytest.raises(ToolError):
        validate("search_knowledge_base", {"query": "gpu", "drop_table": "yes"})


def test_kb_search_finds_gpu_article(api, log):
    text, err = run_tool("search_knowledge_base", {"query": "gpu not detected nvidia-smi"}, api, auto_approver, log)
    assert not err and "KB-1001" in text


def test_declined_write_never_reaches_the_api(api, log):
    text, err = run_tool("create_ticket", {"title": "t", "severity": "sev3-medium", "assigned_queue": "remote-support",
                                           "summary": "s", "customer": "c"}, api, deny_approver, log)
    assert "declined" in text and not err
    with pytest.raises(ToolError):
        api.get_ticket("TKT-5001")
    assert '"approved": false' in log.path.read_text()


def test_offline_run_creates_ticket_and_dispatches_part(api, log):
    request = Path("sample_tickets/gpu_missing.txt").read_text()
    result = run_offline(request, api, auto_approver, log)
    assert result.startswith("TKT-") and "KB-1001" in result
    ticket = api.get_ticket(result.split(" ")[0])
    assert ticket["dispatch_part"] == "GPU-H100-SXM5-80G" and ticket["status"] == "pending-part"


# ---- agent loop with a fake Claude client (no network, no API key) ----

def _msg(stop_reason, blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=blocks, stop_details=None,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _tool(id_, name, inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


class FakeClient:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot: the loop keeps appending
        return self.scripted.pop(0)


def test_agent_loop_runs_tools_and_respects_declined_write(api, log):
    fake = FakeClient([
        _msg("tool_use", [_tool("t1", "search_knowledge_base", {"query": "psu redundancy"})]),
        _msg("tool_use", [_tool("t2", "create_ticket", {"title": "PSU fault", "severity": "sev2-high",
                                                       "assigned_queue": "field-dispatch", "summary": "KB-1003",
                                                       "customer": "Contoso"})]),
        _msg("end_turn", [SimpleNamespace(type="text", text="Recommend dispatching a PSU; ticket was not approved.")]),
    ])
    result = run_agent("PSU amber light", api, deny_approver, log, client=fake)
    assert "Recommend" in result
    # second request carried the KB result back to the model
    tool_result = fake.calls[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and "KB-1003" in tool_result["content"]
    # third request told the model the write was declined
    declined = fake.calls[2]["messages"][-1]["content"][0]["content"]
    assert "declined" in declined
    assert all(c["model"] == "claude-opus-5-5" for c in fake.calls)
