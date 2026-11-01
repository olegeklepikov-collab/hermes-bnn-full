"""Explicit create-only artifact adapter; no general shell or network authority."""
from pathlib import Path
import hashlib
import hmac
import os
import re
import secrets
import tempfile
import time
from .codec import canonical, read_json


def artifact_request(arguments):
    if set(arguments) != {"name", "content"} or not isinstance(arguments["content"], str):
        raise ValueError("Exact artifact name and text are required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.(md|txt|json|csv)", arguments["name"]):
        raise ValueError("Artifact must be a plain filename with an allowed text extension")
    raw = arguments["content"].encode("utf-8")
    if len(raw) > 1024 * 1024:
        raise ValueError("Artifact exceeds 1 MiB; split work without truncation")
    return raw


def issue(settings, ledger, sid, arguments, ttl, reason):
    from adapters.host_guard import request_digest
    artifact_request(arguments)
    if type(ttl) is not int or not 1 <= ttl <= 3600 or not reason.strip():
        raise ValueError("Explicit reason and a lifetime of 1–3600 seconds are required")
    family = ledger.lookup(sid)["session"]["family"]
    grant_id = secrets.token_hex(16)
    body = {"version": 1, "id": grant_id, "family": family, "tool": "gsd_save_artifact",
            "request_digest": request_digest("gsd_save_artifact", arguments),
            "deadline": time.time() + ttl, "precondition": "target_absent", "reason": reason}
    mac = hmac.new(Path(settings["grant_key"]).read_bytes(), canonical(body), hashlib.sha256).hexdigest()
    path = Path(settings["operator_dir"]) / "grants" / (grant_id + ".json")
    path.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(canonical({"body": body, "mac": mac})); f.flush(); os.fsync(f.fileno())
    return {"grant_id": grant_id, "deadline": body["deadline"], "scope": "create_one_exact_artifact"}


def execute(settings, ledger, sid, arguments, grant_id, checkpoint):
    from adapters.host_guard import GuardedDispatcher, request_digest
    raw = artifact_request(arguments)
    if not re.fullmatch(r"[0-9a-f]{32}", grant_id):
        raise ValueError("An operator-issued exact grant is required")
    path = Path(settings["operator_dir"]) / "grants" / (grant_id + ".json")
    grant = read_json(path.read_bytes())
    body = grant["body"]
    key = Path(settings["grant_key"]).read_bytes()
    if path.is_symlink() or not hmac.compare_digest(grant["mac"], hmac.new(key, canonical(body), hashlib.sha256).hexdigest()):
        raise ValueError("Artifact grant authentication failed")
    target_dir = Path(settings["workspace"]) / "artifacts"
    target_dir.mkdir(mode=0o700, exist_ok=True)
    if target_dir.is_symlink() or target_dir.resolve().parent != Path(settings["workspace"]).resolve():
        raise ValueError("Unsafe artifact directory")
    target = target_dir / arguments["name"]
    def authorize(tool, args):
        family = ledger.lookup(sid)["session"]["family"]
        if body["version"] != 1 or body["id"] != grant_id or body["family"] != family or body["tool"] != tool:
            raise ValueError("Grant scope differs")
        if time.time() >= body["deadline"] or body["precondition"] != "target_absent" or target.exists() or target.is_symlink():
            raise ValueError("Grant expired or target precondition changed")
        if body["request_digest"] != request_digest(tool, args):
            raise ValueError("Exact artifact arguments changed")
        ledger.consume_grant(sid, grant_id)
        checkpoint(settings)  # A crash after reservation must not replay this effect.
        return {"allow": True, "request_digest": body["request_digest"]}
    def dispatch(tool, args):
        fd, temporary = tempfile.mkstemp(dir=target_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
            os.chmod(temporary, 0o600)
            # POSIX link creates the name atomically and fails if any writer won the race.
            os.link(temporary, target, follow_symlinks=False)
            result = {"created": True, "path": str(target), "sha256": hashlib.sha256(raw).hexdigest(),
                      "bytes": len(raw), "grant_id": grant_id, "overwritten": False}
            return ledger.grant_result(grant_id, result)
        finally:
            os.unlink(temporary)
    return GuardedDispatcher(authorize, dispatch)("gsd_save_artifact", arguments)
