"""Real DeepSeek calls (opt-in, costs money). T09/T13 live portions."""
import os

import pytest

pytestmark = pytest.mark.live


def test_real_tool_roundtrip():
    if os.environ.get("HARNESS_LIVE") != "1":
        pytest.skip("Set HARNESS_LIVE=1 and provide a valid DEEPSEEK_API_KEY")
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com",
                    timeout=45.0, max_retries=0)
    reply = client.chat.completions.create(
        model="deepseek-flash",
        messages=[{"role": "system", "content": "You are a helpful assistant."},
                  {"role": "user", "content": "Reply with OK."}],
        reasoning_effort="high", extra_body={"thinking": {"type": "enabled"}},
    )
    assert reply.choices[0].message.content
    assert getattr(reply, "id", None), "live call must yield a real request id"
