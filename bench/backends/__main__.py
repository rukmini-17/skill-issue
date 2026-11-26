"""Small CLI used by the pilot scripts. Never sends a chat request.

    python -m bench.backends list                    # models in the models file
    python -m bench.backends show qwen3-8b-llamacpp  # resolved config (no key)
    python -m bench.backends serve-cmd qwen3-8b-llamacpp
    python -m bench.backends get qwen3-8b-llamacpp partition
    python -m bench.backends wait qwen3-8b-llamacpp --timeout 900
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys

from bench.backends import load_models, make_model, model_config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.backends")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for c in ("show", "serve-cmd"):
        sub.add_parser(c).add_argument("model")
    g = sub.add_parser("get")
    g.add_argument("model")
    g.add_argument("key", help="partition | port | base_url | model_file | backend | <any key>")
    w = sub.add_parser("wait")
    w.add_argument("model")
    w.add_argument("--timeout", type=float, default=600.0)
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for name, c in sorted(load_models().items()):
            c = c or {}
            print(f"{name:24} {c.get('backend', '?'):9} {c.get('quantization') or '-':8} "
                  f"{'candidate' if c.get('candidate') else ''}")
        return 0
    if a.cmd == "show":
        c = model_config(a.model)
        c.pop("api_key", None)
        print(json.dumps(c, indent=1))
        return 0
    if a.cmd == "get":
        if a.key == "port":
            print(make_model(a.model).port or "")
        else:
            v = model_config(a.model).get(a.key)
            print("" if v is None else v)
        return 0
    m = make_model(a.model)
    if a.cmd == "serve-cmd":
        print(shlex.join(m.server_command()))
        return 0
    ok = m.wait_ready(a.timeout)                      # wait
    print(f"{a.model}: {'ready' if ok else 'not ready'} at {m.health_url()}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
