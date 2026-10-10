"""Execute a model-router decision through a configured OpenAI backend."""

import argparse
import json
import time
import urllib.error
from pathlib import Path

from openjiuwen import Feedback, Outcome, Router

from verify_serving import post


def execute(router, backends, messages, session_id):
    decision = router.route_sync(
        {"messages": messages, "session_id": session_id, "agent_id": "ascend-host"}
    )
    model_id = decision.selected_model_id
    if model_id not in backends:
        raise ValueError("selected model has no registered backend: " + model_id)
    target = backends[model_id]
    started = time.perf_counter()
    outcome = Outcome.OK
    try:
        response = post(
            target["base_url"],
            "/v1/chat/completions",
            {
                "model": target["model"],
                "messages": messages,
                "max_tokens": 64,
                "temperature": 0,
                "stream": False,
            },
        )
        if not response.get("choices") or not isinstance(response.get("usage"), dict):
            raise ValueError("incomplete backend response")
        return {"selected_model_id": model_id, "response": response}
    except urllib.error.HTTPError as error:
        outcome = (
            Outcome.UNAVAILABLE
            if error.code >= 500 or error.code == 429
            else Outcome.REJECTED
        )
        raise
    except (urllib.error.URLError, TimeoutError):
        outcome = Outcome.UNAVAILABLE
        raise
    except ValueError:
        outcome = Outcome.REJECTED
        raise
    finally:
        latency = int((time.perf_counter() - started) * 1000)
        router.report_sync(
            Feedback.ok(
                decision,
                latency_ms=latency,
                session_id=session_id,
                agent_id="ascend-host",
                outcome=outcome,
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--backends", type=Path, required=True)
    parser.add_argument("--session-id", default="ascend-host-check")
    parser.add_argument("prompt")
    args = parser.parse_args()
    result = execute(
        Router.from_config(str(args.config)),
        json.loads(args.backends.read_text()),
        [{"role": "user", "content": args.prompt}],
        args.session_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
