"""The agent loop: Claude decides which tools to call, this code runs them.

Self-hosted manual loop on the Claude Messages API, so the approval gate,
logging and error handling are all visible in plain Python.
"""

import anthropic

from .tools import TOOLS, SupportAPI, run_tool

MODEL = "claude-opus-5-5"
MAX_TURNS = 12

SYSTEM_PROMPT = """You are a triage agent for an AI-server technical support team.
For each incoming customer request:
1. Search the knowledge base with the customer's symptoms.
2. If the matching article names a replacement part, check its availability.
3. Open one ticket with a clear title, a severity, the right queue, and a summary that cites the KB article ID, what the customer already tried, and the next step.
   - sev1-critical: production training or inference is down.
   - sev2-high: degraded performance or lost redundancy.
   - sev3-medium / sev4-low: everything else.
   - Use field-dispatch when a part must be replaced on site, remote-support when the fix is software or firmware, engineering-escalation when nothing in the KB matches.
4. If a part is needed, update the ticket with dispatch_part and status pending-part, and note the depot and lead time.
Base every statement on tool results; say so plainly when the KB has no match.
Write actions need human approval. If one is declined, do not retry it; say what you recommend instead.
Finish with a short summary for the support engineer: ticket ID, severity, diagnosis, next step."""


def run_agent(request_text: str, api: SupportAPI, approve, log, client: anthropic.Anthropic | None = None) -> str:
    client = client or anthropic.Anthropic()
    messages = [{"role": "user", "content": request_text}]
    log.event("start", model=MODEL, request=request_text)

    for turn in range(MAX_TURNS):
        try:
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise SystemExit("No valid Anthropic credentials. Set ANTHROPIC_API_KEY or run `ant auth login`, "
                             "or use --offline for the scripted demo.")
        except anthropic.RateLimitError as e:
            log.event("api_error", kind="rate_limit", detail=str(e))
            raise
        except anthropic.APIStatusError as e:
            log.event("api_error", kind="status", status=e.status_code, detail=str(e))
            raise
        except anthropic.APIConnectionError as e:
            log.event("api_error", kind="connection", detail=str(e))
            raise

        log.event("model_turn", turn=turn, stop_reason=response.stop_reason,
                  input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)

        if response.stop_reason == "refusal":
            log.event("refusal", details=str(response.stop_details))
            return "The model declined this request. Route it to a human engineer."

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason == "max_tokens":
            return "Stopped: the response hit max_tokens before finishing."

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "end_turn" or not tool_calls:
            final = "\n".join(b.text for b in response.content if b.type == "text").strip()
            log.event("finish", summary=final)
            return final

        results = []
        for call in tool_calls:
            text, is_error = run_tool(call.name, call.input, api, approve, log)
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})

    log.event("finish", summary="stopped: turn limit reached")
    return f"Stopped after {MAX_TURNS} turns without finishing."
