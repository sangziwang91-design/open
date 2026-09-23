import os
import re
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path

_SECRET_NAME = re.compile(r"(?:^|_)(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASS|CREDENTIALS?)(?:_|$)", re.IGNORECASE)
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b"),
)


def redact_sensitive_text(
    text: str,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Remove common credential shapes and secret-valued environment data."""
    redacted = str(text)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("<REDACTED_SECRET>", redacted)
    source = os.environ if environment is None else environment
    secret_values = {
        value
        for key, value in source.items()
        if value and len(value) >= 8 and _SECRET_NAME.search(key)
    }
    for value in sorted(secret_values, key=len, reverse=True):
        redacted = redacted.replace(value, "<REDACTED_SECRET>")
    return redacted



def load_or_create_token(path: Path) -> tuple[str, bool]:
    """Load a local bearer token, or atomically create a private one."""
    token_path = path.expanduser().resolve()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    if token_path.is_symlink():
        raise ValueError("bridge token file must not be a symbolic link")
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(token_path, flags, 0o600)
    except FileExistsError:
        pass
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
        created = True
    if token_path.is_symlink() or not token_path.is_file():
        raise ValueError("bridge token path must be a regular file")
    if os.name != "nt":
        mode = stat.S_IMODE(token_path.stat().st_mode)
        if mode & 0o077:
            token_path.chmod(0o600)
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32 or len(token) > 256 or any(char.isspace() for char in token):
        raise ValueError("bridge token must be 32-256 non-whitespace characters")
    return token, created
