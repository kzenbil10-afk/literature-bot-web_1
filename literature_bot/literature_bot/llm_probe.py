"""Standalone diagnostic: probes NVIDIA NIM (and optionally Anthropic) to see
which models your API key can actually reach right now.

NVIDIA's free-tier model catalog turns over quickly -- models get retired
(HTTP 410 "Gone") with little warning, sometimes including ones that worked
last month. If `search --deep-research` or `draft` suddenly falls back to the
no-LLM path ("... anahtar yok/hata -> çıkarımsal özet kullanılacak" / "kural
tabanlı bir iskelet taslak üretilecek"), run this to find out which model (if
any) your key can currently reach, instead of guessing model names one at a
time.

Usage:
    python -m literature_bot.llm_probe                    # tests whichever of
                                                            # NVIDIA_API_KEY /
                                                            # ANTHROPIC_API_KEY
                                                            # are set
    python -m literature_bot.llm_probe --provider nvidia
    python -m literature_bot.llm_probe --provider nvidia --model meta/llama-3.1-8b-instruct
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

# Known NVIDIA NIM model slugs worth trying, roughly newest/most-likely-active
# first. This list will inevitably go stale as NVIDIA's catalog changes --
# that's exactly why this probe exists instead of hardcoding one "the" model.
NVIDIA_CANDIDATES = [
    "mistralai/mistral-nemotron",
    "meta/llama-3.1-8b-instruct",
    "meta/llama-3.1-405b-instruct",
    "meta/llama-3.3-70b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "mistralai/mixtral-8x22b-instruct-v0.1",
    "qwen/qwen2.5-72b-instruct",
    "qwen/qwen3.5-122b-a10b",
    "google/gemma-2-27b-it",
    "deepseek-ai/deepseek-r1",
    "deepseek-ai/deepseek-v4-pro",
    "openai/gpt-oss-120b",
]

ANTHROPIC_CANDIDATES = [
    "claude-sonnet-4-5",
]


def _probe_nvidia(api_key: str, models: Optional[List[str]] = None) -> None:
    try:
        from openai import OpenAI
    except ImportError:
        print("[hata] 'openai' paketi kurulu değil -- önce: pip install openai", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
    client = OpenAI(api_key=api_key, base_url=base_url)
    for model in (models or NVIDIA_CANDIDATES):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=20,
                messages=[{"role": "user", "content": "Merhaba, kisaca cevap ver."}],
            )
            text = (resp.choices[0].message.content or "").replace("\n", " ")[:70]
            print(f"CALISIYOR  | {model:<45} -> {text}")
        except Exception as e:
            msg = str(e).replace("\n", " ")[:110]
            print(f"basarisiz  | {model:<45} -> {type(e).__name__}: {msg}")


def _probe_anthropic(api_key: str, models: Optional[List[str]] = None) -> None:
    try:
        import anthropic
    except ImportError:
        print("[hata] 'anthropic' paketi kurulu değil -- önce: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    for model in (models or ANTHROPIC_CANDIDATES):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=20,
                messages=[{"role": "user", "content": "Merhaba, kisaca cevap ver."}],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text")).replace("\n", " ")[:70]
            print(f"CALISIYOR  | {model:<45} -> {text}")
        except Exception as e:
            msg = str(e).replace("\n", " ")[:110]
            print(f"basarisiz  | {model:<45} -> {type(e).__name__}: {msg}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m literature_bot.llm_probe",
        description="NVIDIA_API_KEY / ANTHROPIC_API_KEY ile hangi modellerin şu an gerçekten "
        "çalıştığını test eder (NVIDIA'nın ücretsiz katalogu sık değiştiği için).",
    )
    parser.add_argument(
        "--provider", choices=["nvidia", "anthropic"], default=None,
        help="Sadece bu sağlayıcıyı test et (verilmezse hangi anahtar(lar) ortamda tanımlıysa onlar test edilir)",
    )
    parser.add_argument(
        "--model", action="append", default=None,
        help="Varsayılan aday listesi yerine sadece bu model(ler)i test et (birden fazla kez verilebilir)",
    )
    args = parser.parse_args(argv)

    providers_to_test: List[str] = []
    if args.provider:
        providers_to_test = [args.provider]
    else:
        if os.environ.get("NVIDIA_API_KEY"):
            providers_to_test.append("nvidia")
        if os.environ.get("ANTHROPIC_API_KEY"):
            providers_to_test.append("anthropic")

    if not providers_to_test:
        print(
            "Ne NVIDIA_API_KEY ne de ANTHROPIC_API_KEY ortamda tanımlı. Önce birini "
            "tanımlayın (bkz. README.md 'NVIDIA API ile kurulum (adım adım)' bölümü), "
            "sonra bu komutu tekrar çalıştırın.",
            file=sys.stderr,
        )
        return 2

    for provider in providers_to_test:
        print(f"\n=== {provider.upper()} ===")
        key = os.environ.get(f"{provider.upper()}_API_KEY")
        if not key:
            print(f"[uyarı] {provider.upper()}_API_KEY tanımlı değil, atlanıyor.")
            continue
        if provider == "nvidia":
            _probe_nvidia(key, models=args.model)
        elif provider == "anthropic":
            _probe_anthropic(key, models=args.model)

    print(
        "\nÇalışan (CALISIYOR) bir model bulduysanız:\n"
        "  tek seferlik   -> --model <model-adi>\n"
        "  kalıcı olarak  -> ortam değişkeni: LLM_MODEL=<model-adi>"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
