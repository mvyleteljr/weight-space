import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .experiment import run
from .network import encode, fingerprint, forward, initialize, load, save, validate
from .providers import tinfoil_models
from .records import record
from .bundle import read_bundle, identity, validate_bundle
from .security import CODE_DISABLED
from .game import match
from Street_Fighter.src.arena import specification


def main():
    parser = argparse.ArgumentParser(description="Create and test directly programmed network weights.")
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe", help="Show all layer activations for one observation.")
    probe.add_argument("path", type=Path)
    probe.add_argument("--inputs", type=float, nargs="+", required=True)
    commands.add_parser("game-spec", help="Show model observations and actions for Street Fighter.")
    game = commands.add_parser("match", help="Run two dense JSON networks in Street Fighter.")
    game.add_argument("first", type=Path)
    game.add_argument("second", type=Path)
    game.add_argument("--output", type=Path, required=True)
    game.add_argument("--max-steps", type=int, default=3600)
    init = commands.add_parser("init", help="Create a fresh network file.")
    init.add_argument("path", type=Path)
    init.add_argument("--sizes", nargs="+", type=int, default=[2, 4, 1])
    init.add_argument("--seed", type=int, default=0)
    init.add_argument("--zero", action="store_true")
    check = commands.add_parser("inspect", help="Check network shape and parameter values.")
    check.add_argument("path", type=Path)
    evaluate = commands.add_parser("evaluate", help="Test XOR and save the model and feedback.")
    evaluate.add_argument("path", type=Path)
    evaluate.add_argument("--records", type=Path, default=Path("runs/manual"))
    evaluate.add_argument("--note", default="Manual evaluation.")
    live = commands.add_parser("run", help="Run a live agent through the feedback loop.")
    live.add_argument("--provider", choices=["codex", "claude", "tinfoil"], required=True)
    live.add_argument("--model", required=True)
    live.add_argument("--output", type=Path, required=True, help="A new directory for this run.")
    live.add_argument("--rounds", type=int, default=2)
    live.add_argument("--seed", type=int, default=0)
    live.add_argument("--format", choices=["dense"], default="dense",
                      help="Only data-only dense models are accepted.")
    live.add_argument("--timeout", type=int, default=180)
    live.add_argument("--max-tokens", type=int, default=20000,
                      help="Token limit per Tinfoil call, including reasoning tokens.")
    commands.add_parser("doctor", help="Check local tools and key presence. Makes no model calls.")
    models = commands.add_parser("models", help="List public Tinfoil model IDs. No key needed.")
    models.add_argument("--filter", default="")
    args = parser.parse_args()
    try:
        if args.command == "probe":
            print(encode(forward(load(args.path), args.inputs, return_trace=True)))
        elif args.command == "game-spec":
            print(encode(specification()))
        elif args.command == "match":
            print(encode(match(args.first, args.second, args.output, args.max_steps)))
        elif args.command == "init":
            if args.path.exists():
                raise ValueError("The model file exists. Select a new path.")
            save(args.path, initialize(args.sizes, args.seed, args.zero))
            print(args.path)
        elif args.command == "inspect":
            if args.path.is_dir():
                bundle = read_bundle(args.path)
                print(encode({**validate_bundle(bundle), **identity(bundle)}))
                return 0
            model = load(args.path)
            print(encode({"parameters": validate(model), "sha256": fingerprint(model),
                          "sizes": [model["input_size"]] + [len(l["bias"]) for l in model["layers"]]}))
        elif args.command == "evaluate":
            if args.path.is_dir():
                raise ValueError(CODE_DISABLED)
            else:
                directory, result = record(args.records, load(args.path), args.note)
            print(encode({"record": str(directory), **result}))
        elif args.command == "run":
            summary = run(args.output, args.provider, args.model, args.rounds,
                          args.seed, args.timeout, args.max_tokens, args.format)
            print(encode(summary))
            return 0 if summary["status"] == "passed" else 1
        elif args.command == "doctor":
            print(encode({"python": sys.version.split()[0],
                          "codex": shutil.which("codex"), "claude": shutil.which("claude"),
                          "tinfoil_key_set": bool(os.environ.get("TINFOIL_API_KEY")),
                          "note": "Tool presence does not confirm model access."}))
        elif args.command == "models":
            print(encode([m for m in tinfoil_models()
                          if args.filter.lower() in (m["id"] + " " + m.get("name", "")).lower()]))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
