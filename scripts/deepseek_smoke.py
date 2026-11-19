"""Minimal NON-STREAMING probe for the configured DeepSeek endpoint.

Reads DEEPSEEK_API_KEY from the local environment only. Not executed by the
offline suite. Only run when the maintainer has enabled live testing (costs money).
"""
import os

from openai import OpenAI


def main() -> None:
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        timeout=45.0,
        max_retries=0,
    )
    reply = client.chat.completions.create(
        model="deepseek-flash",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with OK."},
        ],
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}},
    )
    print(reply.choices[0].message.content)


if __name__ == "__main__":
    main()
