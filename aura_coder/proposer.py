"""Optional LLM patch proposer behind the same interface as the AST operators (not used by the benchmark).

An operator is `fn(src, feats) -> iterator of candidate sources`. If AURA_CODER_LLM_URL is set (an
OpenAI-compatible /v1/chat/completions endpoint, key in AURA_CODER_LLM_KEY, model in AURA_CODER_LLM_MODEL),
`register()` adds an `llm_patch` operator; the Aura policy can then rank it like any other operator
(it is not in the seed `default-order`, so a rule has to promote it). Offline runs never touch the network.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

PROMPT = ("Fix the bug in this Python module so its tests pass. Reply with the full corrected module in one "
          "```python block and nothing else.\nFailure: {etype}: {msg}\n\n```python\n{src}```")


def llm_patch(src: str, feats: dict, n: int = 1):
    url = os.environ.get("AURA_CODER_LLM_URL")
    if not url:
        return
    body = {"model": os.environ.get("AURA_CODER_LLM_MODEL", "default"), "n": n, "temperature": 0.2,
            "messages": [{"role": "user", "content": PROMPT.format(src=src, **{k: feats.get(k, "") for k in
                                                                          ("etype", "msg")})}]}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json",
                                 "Authorization": "Bearer " + os.environ.get("AURA_CODER_LLM_KEY", "")})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    for ch in out.get("choices", []):
        m = re.search(r"```python\n(.*?)```", ch["message"]["content"], re.S)
        if m:
            yield m.group(1)


def register() -> bool:
    from .operators import OPERATORS
    if os.environ.get("AURA_CODER_LLM_URL"):
        OPERATORS["llm_patch"] = llm_patch
        return True
    return False
