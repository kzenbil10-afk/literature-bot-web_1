"""Unified LLM client used by translation.py and synthesis.py.

The rest of the codebase doesn't need to know or care which LLM backend is
configured -- it just calls `chat_complete(prompt, ...)` and gets text back
(or None, if nothing is configured or the call failed; callers always have a
non-LLM fallback for that case).

Three backends are supported:
  - "anthropic": Claude, via the `anthropic` package. Needs ANTHROPIC_API_KEY.
                 Paid (no free tier), but fast and reliable -- see
                 https://platform.claude.com/docs/en/about-claude/pricing.
  - "openai":    OpenAI's own API (https://api.openai.com), via the `openai`
                 package. Needs OPENAI_API_KEY. Paid (no free tier); the
                 default model (gpt-5.6-luna) is OpenAI's cheapest/fastest
                 tier -- see https://platform.openai.com/docs/pricing.
  - "nvidia":     any model hosted on NVIDIA's OpenAI-compatible NIM endpoint
                  (https://build.nvidia.com -- "Get API Key" on a model page
                  gives you a key that starts with "nvapi-"). Needs
                  NVIDIA_API_KEY. Free, but the free tier is noticeably
                  slower/less reliable than the two paid options above (see
                  the bounded-retry logic below).

"openai" and "nvidia" both speak the OpenAI chat completions protocol, so
they share `_call_openai_compatible()` below and differ only in which base
URL and key they use.

Provider selection, in order:
  1. an explicit `provider=` argument,
  2. the LLM_PROVIDER environment variable ("anthropic", "openai", or "nvidia"),
  3. auto-detect from whichever API key is set -- ANTHROPIC_API_KEY wins if
     several happen to be set, then OPENAI_API_KEY, then NVIDIA_API_KEY;
     override with LLM_PROVIDER if you want a different one used instead.

Model selection, in order:
  1. an explicit `model=` argument,
  2. the LLM_MODEL environment variable,
  3. a sensible per-provider default (see _DEFAULT_MODELS below).
"""
from __future__ import annotations

import os
from typing import Optional

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    # OpenAI's cheapest/fastest current tier (as of 2026-09-24); override with
    # --model / LLM_MODEL for a stronger (pricier) model if quality matters
    # more than cost/speed for your use case.
    "openai": "gpt-5.6-luna",
    # NVIDIA's free-tier catalog turns over quickly -- older Llama models
    # (including the previous default, meta/llama-3.3-70b-instruct) have been
    # retired (HTTP 410). mistralai/mistral-nemotron was verified working and
    # instruction-following (incl. Turkish) as of 2026-09-24; override with
    # --model / LLM_MODEL if NVIDIA retires this one too.
    "nvidia": "mistralai/mistral-nemotron",
}

# NVIDIA's OpenAI-compatible NIM endpoint (build.nvidia.com). Override with
# NVIDIA_BASE_URL if you're pointing at a self-hosted NIM instead of the
# cloud one. OpenAI itself needs no base_url override -- the `openai` package
# defaults to api.openai.com already.
_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def detect_provider(explicit: Optional[str] = None) -> Optional[str]:
    """Figures out which provider to use, or None if nothing is configured."""
    if explicit:
        return explicit
    env_provider = os.environ.get("LLM_PROVIDER")
    if env_provider:
        return env_provider.strip().lower()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("NVIDIA_API_KEY"):
        return "nvidia"
    return None


def default_model(provider: str) -> str:
    return os.environ.get("LLM_MODEL") or _DEFAULT_MODELS.get(provider, _DEFAULT_MODELS["anthropic"])


def is_configured(provider: Optional[str] = None) -> bool:
    return detect_provider(provider) is not None


# Free/shared LLM endpoints (this applies to NVIDIA NIM's free tier in
# particular) occasionally accept a connection and then never respond --
# no error, just silence -- rather than failing cleanly. Without an explicit
# timeout, the underlying SDKs default to very long waits (and several
# retries each), so a single flaky call could block the whole CLI for
# minutes. We use a short per-attempt timeout plus a couple of our own fast
# retries instead, so a bad attempt is abandoned quickly and a good one
# (usually the 1st or 2nd) gets used.
_REQUEST_TIMEOUT_SECONDS = 30
_MAX_ATTEMPTS = 3


def _call_anthropic(prompt: str, api_key: str, model: str, max_tokens: int) -> Optional[str]:
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic(api_key=api_key, timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=0)
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in resp.content if hasattr(b, "text"))
        except Exception:
            if attempt == _MAX_ATTEMPTS - 1:
                return None
            continue
    return None


def _call_openai_compatible(
    prompt: str, api_key: str, model: str, max_tokens: int, base_url: Optional[str] = None
) -> Optional[str]:
    """Shared by "openai" (base_url=None -> api.openai.com) and "nvidia"
    (base_url=NVIDIA's NIM endpoint) -- both speak the same protocol."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=0)
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=0.4,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content
        except Exception:
            if attempt == _MAX_ATTEMPTS - 1:
                return None
            continue
    return None


def chat_complete(
    prompt: str,
    model: Optional[str] = None,
    max_tokens: int = 4000,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
) -> Optional[str]:
    """Sends a single user-turn prompt to whichever provider is configured.

    Never raises -- returns None on any failure (missing key, missing
    package, network/API error, ...) so callers can transparently fall back
    to a non-LLM path.
    """
    resolved_provider = detect_provider(provider)
    if resolved_provider is None:
        return None

    if resolved_provider == "anthropic":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        return _call_anthropic(prompt, key, model or default_model("anthropic"), max_tokens)

    if resolved_provider == "openai":
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            return None
        return _call_openai_compatible(prompt, key, model or default_model("openai"), max_tokens)

    if resolved_provider == "nvidia":
        key = api_key or os.environ.get("NVIDIA_API_KEY")
        if not key:
            return None
        base_url = os.environ.get("NVIDIA_BASE_URL") or _NVIDIA_BASE_URL
        return _call_openai_compatible(prompt, key, model or default_model("nvidia"), max_tokens, base_url=base_url)

    # Unknown provider name -> nothing we can do.
    return None
