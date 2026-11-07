"""Compare complete weight-edit loops with the same initial model and feedback."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time

from .demo import publish
from .game import match
from .lab import WeightLab
from .network import initialize, save, encode
from .tool_loop import run_agent


def run(output, models, reply_timeout=25, edit_seconds=50):
    parsed = []
    for entry in models:
        provider, separator, model = entry.partition(":")
        if provider not in ("codex", "claude", "tinfoil") or not separator or not model:
            raise ValueError("Use provider:model for each candidate.")
        parsed.append((provider, model))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    save(output / "initial.json", initialize([31, 8, 18], seed=42))
    match(output / "initial.json", output / "initial.json", output / "before", 1800)
    results = []

    def test(index, provider, model):
        lab = WeightLab(output / "initial.json", output / "before", output / f"candidate-{index}", 1)
        start = time.monotonic()
        result = {"provider": provider, "model": model}
        try:
            result.update(run_agent(lab, provider, model, edit_seconds, reply_timeout), status="submitted")
        except Exception as error:
            result.update(status="failed", error=type(error).__name__, detail=str(error))
        result.update(seconds=round(time.monotonic() - start, 2), test_cases=lab.test_cases,
                      tool_calls=lab.calls, revisions=lab.revision)
        publish(lab.directory / "benchmark.json", result)
        return result

    with ThreadPoolExecutor(max_workers=min(4, len(parsed))) as pool:
        pending = [pool.submit(test, i + 1, provider, model) for i, (provider, model) in enumerate(parsed)]
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            publish(output / "results.json", results)
            print(encode(result), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--reply-timeout", type=float, default=25)
    parser.add_argument("--edit-seconds", type=float, default=50)
    args = parser.parse_args()
    run(args.output, args.models, args.reply_timeout, args.edit_seconds)
