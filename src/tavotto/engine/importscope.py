"""Identity of an asset or script in an OmicOS import batch (stdlib only)."""

from pathlib import Path, PurePosixPath


def namespace(relative: str) -> str:
    parts = PurePosixPath(str(relative).replace("\\", "/")).parts
    if len(parts) >= 3 and parts[0] == "imports" and parts[1] not in (".", ".."):
        return "/".join(parts[:2])
    return ""


def key(relative: str, stem: str | None = None) -> str:
    """Qualified lookup/history key; never passed to the drawing worker."""
    path = PurePosixPath(str(relative).replace("\\", "/"))
    local = path.stem if stem is None else stem
    scope = namespace(relative)
    return scope + "/" + local if scope else local


def local_claim(script: str, stem: str) -> str:
    """Accept this batch's qualified UI claim, reject cross-batch reassignment."""
    scope = namespace(script)
    claimed_scope = namespace(stem)
    if claimed_scope:
        if claimed_scope != scope:
            raise RuntimeError("An imported figure cannot be assigned to another source batch")
        stem = stem[len(scope) + 1 :]
    if scope and ("/" in stem or "\\" in stem or stem in (".", "..")):
        raise RuntimeError("Imported figure stems must be local output names")
    return stem


def original_artifact(project_root: str, script: str, stem: str, extensions) -> str | None:
    """Find only this batch's original. Ambiguous same-stem locations stay unbound."""
    root = Path(project_root).resolve()
    scope = namespace(script)
    if not scope:
        return None
    base = root / scope
    candidates = []
    for suffix in extensions:
        for path in sorted(base.rglob("*" + suffix)):
            if path.stem != stem or not path.is_file():
                continue
            if not path.resolve().is_relative_to(base.resolve()):
                continue
            candidates.append(path)
        if candidates:
            break
    return candidates[0].relative_to(root).as_posix() if len(candidates) == 1 else None
