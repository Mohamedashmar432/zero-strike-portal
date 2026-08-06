"""Deterministic pre-LLM triage for AI Auto-Fix (see docs/AI_AUTOFIX_DESIGN.md).

Answers one question with zero LLM calls and zero DB reads: could an agent run on this finding
*possibly* produce a patch the apply step would accept? When the answer is provably no, the
propose loop writes a can_fix=False proposal directly and skips the agent -- saving a full
tool-calling run (and its tokens) per hopeless finding, and giving the reviewer a straight answer
instead of a vague "the agent could not produce a fix".

Pure and DB-free, like remediation_tools' helpers, so it unit-tests without mongomock.

Every rule here must be *provable*, not a heuristic guess about fix difficulty -- deciding a fix
is "too hard" is the agent's job (it returns can_fix=False honestly). These rules only encode
mechanical impossibility. The secret rule in particular is justified by
tests/test_remediation_triage.py, which proves the redaction/apply dead end it avoids.
"""

from dataclasses import dataclass
from typing import Literal

from app.models.finding import Finding
from app.services.remediation_tools import _SKIP_DIRS

# "code-patch"       -> ordinary single-file source fix; run the agent
# "dependency-bump"  -> SCA manifest version bump; run the agent (it has the fixed version)
# "rotate-secret"    -> a human must rotate + move the value; a patch can't express it
# "none"             -> nothing an agent could act on
FixStrategy = Literal["code-patch", "dependency-bump", "rotate-secret", "none"]

# Extensions whose bytes an exact-substring text patch cannot meaningfully edit.
_BINARY_EXTS = {
    "png", "jpg", "jpeg", "gif", "bmp", "ico", "webp", "svgz", "pdf", "zip", "gz", "tar",
    "bz2", "xz", "7z", "rar", "jar", "war", "class", "so", "dylib", "dll", "exe", "bin",
    "o", "a", "obj", "pyc", "pyo", "wasm", "woff", "woff2", "ttf", "eot", "otf", "mp3",
    "mp4", "avi", "mov", "webm", "wav", "ogg", "db", "sqlite", "sqlite3", "parquet",
}

# Generated/minified artifacts: editing them is pointless (regenerated from source) and their
# single-line-megabyte shape makes a unique-substring patch unreliable.
_GENERATED_SUFFIXES = (".min.js", ".min.css", ".map", ".bundle.js", ".chunk.js", "-lock.json")
_GENERATED_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock", "gemfile.lock",
    "poetry.lock", "cargo.lock", "go.sum", "packages.lock.json",
}


@dataclass(frozen=True)
class TriageResult:
    eligible: bool
    # User-facing manual_review_reason when not eligible. None when eligible.
    reason: str | None
    strategy: FixStrategy


_ELIGIBLE_CODE = TriageResult(True, None, "code-patch")
_ELIGIBLE_DEP = TriageResult(True, None, "dependency-bump")


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("./")


def _is_vendored(path: str) -> str | None:
    """Returns the offending directory name, or None. A finding inside a dependency/build dir is
    not this repo's code to fix -- patching it is either overwritten on the next install/build, or
    belongs upstream."""
    for part in _norm(path).split("/")[:-1]:
        if part in _SKIP_DIRS:
            return part
    return None


def _is_generated(path: str) -> bool:
    name = _norm(path).rsplit("/", 1)[-1].lower()
    return name in _GENERATED_NAMES or name.endswith(_GENERATED_SUFFIXES)


def _is_binary(path: str) -> bool:
    name = _norm(path).rsplit("/", 1)[-1]
    return "." in name and name.rsplit(".", 1)[-1].lower() in _BINARY_EXTS


def triage(finding: Finding) -> TriageResult:
    """Decide whether to spend an agent run on this finding. Never raises."""
    path = (finding.location.file or "") if finding.location else ""
    if not path.strip():
        return TriageResult(
            False, "The scanner did not record a file for this finding, so there is nothing to patch.", "none"
        )

    vendored = _is_vendored(path)
    if vendored:
        return TriageResult(
            False,
            f"This finding is inside `{vendored}/`, which is dependency or build output rather than "
            "your source. Fix it upstream or by updating the dependency -- a patch here would be "
            "overwritten on the next install/build.",
            "none",
        )

    if _is_generated(path):
        return TriageResult(
            False,
            f"`{_norm(path)}` is a generated or minified artifact. Change the source it is built "
            "from (or the manifest, for a lockfile) rather than the artifact.",
            "none",
        )

    if _is_binary(path):
        return TriageResult(
            False, f"`{_norm(path)}` is a binary file, which cannot be patched as text.", "none"
        )

    if finding.kind == "secret":
        # Proven in tests/test_remediation_triage.py: every path that shows the agent this line
        # redacts the literal first, so any original_code spanning it is absent from the real file
        # and _apply_patch rejects it as "source changed". An agent run here cannot succeed.
        return TriageResult(
            False,
            "A committed secret can't be auto-patched: the value is redacted everywhere the AI can "
            "see it, so it cannot produce a patch that applies. Rotate the credential now (assume "
            "it is compromised -- it is in git history), then replace the literal with a lookup "
            "from your environment or secret manager.",
            "rotate-secret",
        )

    if finding.kind == "sca":
        dep = finding.dependency
        if dep is None or not str(dep.fixed_version or "").strip():
            pkg = f"`{dep.package}`" if dep and dep.package else "this dependency"
            return TriageResult(
                False,
                f"The scanner did not report a fixed version for {pkg}, so there is no safe version "
                "to bump to yet. Track the advisory, or remove/replace the dependency.",
                "none",
            )
        return _ELIGIBLE_DEP

    return _ELIGIBLE_CODE
