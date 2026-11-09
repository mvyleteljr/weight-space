"""Provider calls for a bounded weight-writing test."""

import json
import uuid
from contextlib import nullcontext
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


class ProviderSession:
    """One private CLI conversation for one agent in one run; never discovers old sessions."""
    def __init__(self, provider, model):
        if provider not in ("codex", "claude"):
            raise ValueError("Persistent sessions require a subscription CLI.")
        self.provider, self.model = provider, model
        self.workspace = tempfile.TemporaryDirectory(prefix=f"weight-space-{provider}-")
        self.session_id = None
        self.context_text = None
        self.round = None
        self.history_sent = 0
        self.requests = 0
        self.interrupted = False

    def close(self):
        self.workspace.cleanup()


def codex_session_id(stdout):
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    for line in (stdout or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "thread.started" and event.get("thread_id"):
            return str(uuid.UUID(event["thread_id"]))
    return None


def complete(provider, model, prompt, timeout=180, max_tokens=20000, *, quick=False, output_schema=None, session=None, reasoning_effort=None):
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
    if session is not None and (session.provider, session.model) != (provider, model):
        raise ValueError("Session belongs to a different agent provider/model.")
    workspace = nullcontext(session.workspace.name) if session else tempfile.TemporaryDirectory(prefix="weight-space-")
    with workspace as temp:
        output = Path(temp) / "reply.txt"
        output.unlink(missing_ok=True)
        resumed = bool(session and session.session_id)
        if provider == "codex":
            command = ["codex", "exec", "--model", model, "--sandbox", "read-only",
                       "--disable", "shell_tool",
                       "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
                       "--color", "never", "--output-last-message", str(output), "-"]
        else:
            command = ["claude", "--print", "--model", model, "--output-format", "json",
                       "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                       "--safe-mode", "--no-session-persistence"]
        if session is not None:
            if provider == "codex":
                command.remove("--ephemeral")
                command.insert(2, "--json")
                if resumed:
                    # Parent exec options preserve read-only/no-shell settings on resume.
                    command[-1:] = ["resume", session.session_id, "-"]
            else:
                command.remove("--no-session-persistence")
                if resumed:
                    command.extend(["--resume", session.session_id])
                else:
                    session.session_id = str(uuid.uuid4())
                    command.extend(["--session-id", session.session_id])
            session.requests += 1
        if quick or reasoning_effort is not None:
            effort = reasoning_effort or "low"
            if provider == "codex":
                command[2:2] = ["-c", f'model_reasoning_effort="{effort}"']
            else:
                command.extend(["--effort", effort])
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
        try:
            result = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                    timeout=timeout, cwd=temp, env=environment)
        except subprocess.TimeoutExpired as error:
            if session is not None:
                if provider == "codex":
                    session.session_id = codex_session_id(error.stdout) or session.session_id
                session.interrupted = True
            # The command includes the full schema. Keep it out of user-facing errors.
            raise TimeoutError(f"{provider} did not reply within {timeout:.0f} seconds.") from None
        if result.returncode:
            detail = result.stderr[-1500:]
            if not detail.strip() and provider == "claude":
                try:
                    failure = json.loads(result.stdout)
                    detail = str(failure.get("result") or failure.get("error") or failure.get("errors") or "No error details returned.")[:1500]
                except ValueError:
                    detail = "No structured error details returned."
            raise RuntimeError(f"{provider} exited with status {result.returncode}: "
                               + detail)
        metadata = {"provider": provider, "requested_model": model, "resumed": resumed}
        if session is not None and provider == "codex":
            returned_id = codex_session_id(result.stdout)
            if not returned_id:
                raise RuntimeError("Codex returned no session ID; refusing a context-free continuation.")
            if resumed and returned_id != session.session_id:
                raise RuntimeError("Codex resumed a different session.")
            session.session_id = returned_id
            metadata["session_id"] = returned_id
        if provider == "codex":
            if not output.exists():
                raise RuntimeError("Codex did not write a final reply.")
            return output.read_text(), metadata
        body = json.loads(result.stdout)
        if body.get("is_error"):
            raise RuntimeError("Claude returned an error result. Check subscription access.")
        if session is not None and body.get("session_id") != session.session_id:
            raise RuntimeError("Claude returned a different session ID.")
        metadata.update({"usage": body.get("usage"), "model_usage": body.get("modelUsage"),
                         "session_id": body.get("session_id")})
        if output_schema is not None:
            structured = body.get("structured_output")
            if not isinstance(structured, dict):
                raise RuntimeError("Claude returned no structured output.")
            return json.dumps(structured, allow_nan=False), metadata
        return body["result"], metadata
