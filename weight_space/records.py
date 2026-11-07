"""Write a fresh record for each evaluation. Never overwrite an old round."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .network import encode, fingerprint, save
from .task import evaluate
from .security import CODE_DISABLED


def record(root, model, note="", metadata=None):
    result = evaluate(model)
    result.update({"model_sha256": fingerprint(model), "note": note,
                   "created_at": datetime.now(timezone.utc).isoformat(),
                   "metadata": metadata or {}})
    directory = Path(root) / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "model.json", model)
    (directory / "result.json").write_text(encode(result))
    return directory, result


def record_bundle(root, bundle, note="", metadata=None, timeout=10):
    raise ValueError(CODE_DISABLED)
