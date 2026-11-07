"""Provider calls for a bounded weight-writing test."""

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .network import validate
from .security import CODE_DISABLED

API_ROOT = "https://inference.tinfoil.sh/v1"


def parse_reply(text, model_format="dense"):
    if model_format != "dense":
        raise ValueError(CODE_DISABLED)
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
    reply = json.loads(text)
    if not isinstance(reply, dict) or set(reply) != {"reason", "model"}:
        raise ValueError("Reply must contain reason and model only.")
    if not isinstance(reply["reason"], str) or not reply["reason"].strip():
        raise ValueError("Supply a short reason for the weight values.")
    validate(reply["model"])
    return reply


def tinfoil_models():
    with urllib.request.urlopen(API_ROOT + "/models", timeout=30) as response:
        return [{key: m[key] for key in ("id", "name", "deprecated", "deprecationDate") if key in m}
                for m in json.load(response)["data"]]


def complete(provider, model, prompt, timeout=180, max_tokens=20000, *, quick=False, output_schema=None):
    if not model or model.startswith("SET_"):
        raise ValueError("Set the exact model ID before a live test.")
    if provider == "tinfoil":
        key = os.environ.get("TINFOIL_API_KEY")
        if not key:
            raise ValueError("Set TINFOIL_API_KEY. Use uv run --env-file .env to load a local key.")
        from tinfoil import TinfoilAI

        try:
            client = TinfoilAI(api_key=key, timeout=timeout)
            client.client.max_retries = 0
            try:
                options = {}
                if quick and model in {"deepseek-v4-1-flash", "gemma4-31b", "gpt-oss-120b",
                                       "glm-5-3", "kimi-k3-1-pro"}:
                    options["reasoning_effort"] = "none" if model in {"deepseek-v4-1-flash", "gemma4-31b"} else "low"
                body = client.chat.completions.create(
                    model=model, messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens, stream=False, **options,
                ).model_dump()
            finally:
                client.client.close()
        except Exception as error:
            # Do not put provider response bodies or credentials in saved error records.
            raise RuntimeError(f"Tinfoil request failed ({type(error).__name__}). "
                               "Check the key, model access, service status, and timeout.") from None
        choice = body["choices"][0]
        text = choice["message"].get("content")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Tinfoil returned no text. Check the token limit and model.")
        return text, {"provider": provider, "requested_model": model,
                      "resolved_model": body.get("model"), "usage": body.get("usage"),
                      "response_id": body.get("id"), "finish_reason": choice.get("finish_reason")}

    executable = {"codex": "codex", "claude": "claude"}.get(provider)
    if executable is None or shutil.which(executable) is None:
        raise ValueError(f"Provider CLI is unavailable: {provider}")
    with tempfile.TemporaryDirectory(prefix="weight-space-") as temp:
        output = Path(temp) / "reply.txt"
        if provider == "codex":
            command = ["codex", "exec", "--model", model, "--sandbox", "read-only",
                       "--disable", "shell_tool",
                       "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
                       "--color", "never", "--output-last-message", str(output), "-"]
        else:
            command = ["claude", "--print", "--model", model, "--output-format", "json",
                       "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                       "--safe-mode", "--no-session-persistence"]
        if quick:
            if provider == "codex":
                command[2:2] = ["-c", 'model_reasoning_effort="low"']
            else:
                command.extend(["--effort", "low"])
        if output_schema is not None:
            if provider == "codex":
                schema_path = Path(temp) / "reply-schema.json"
                schema_path.write_text(json.dumps(output_schema, allow_nan=False))
                command[2:2] = ["--output-schema", str(schema_path)]
            else:
                command.extend(["--json-schema", json.dumps(output_schema, separators=(",", ":"))])
        # Run in an empty directory. Do not give either CLI the other agents' records.
        environment = os.environ.copy()
        for name in ("TINFOIL_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            environment.pop(name, None)
        result = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                timeout=timeout, cwd=temp, env=environment)
        if result.returncode:
            raise RuntimeError(f"{provider} exited with status {result.returncode}: "
                               + result.stderr[-1500:])
        metadata = {"provider": provider, "requested_model": model}
        if provider == "codex":
            if not output.exists():
                raise RuntimeError("Codex did not write a final reply.")
            return output.read_text(), metadata
        body = json.loads(result.stdout)
        if body.get("is_error"):
            raise RuntimeError("Claude returned an error result. Check subscription access.")
        metadata.update({"usage": body.get("usage"), "model_usage": body.get("modelUsage"),
                         "session_id": body.get("session_id")})
        if output_schema is not None:
            structured = body.get("structured_output")
            if not isinstance(structured, dict):
                raise RuntimeError("Claude returned no structured output.")
            return json.dumps(structured, allow_nan=False), metadata
        return body["result"], metadata
