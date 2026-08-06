"""Deterministic pre-LLM triage for AI Auto-Fix.

The first test group is the *justification* for the secret-finding triage rule, not a test of
triage itself: it proves that a hardcoded-secret finding can never produce an appliable patch,
because every path that shows the agent the offending line redacts the literal first. Without
that proof the rule would just be a guess, so it is asserted here and the rule depends on it.
"""

import pytest

from app.models.finding import DependencyEmbedded, Finding, LocationEmbedded
from app.services import secret_redaction
from app.services.ai_remediation_apply_service import _ManualReview, _apply_patch
from app.services.remediation_triage import triage

# A realistic hardcoded-secret line: high entropy, secret-looking key, so both the pattern pass
# and the entropy pass in secret_redaction fire on it.
SECRET_LINE = 'API_KEY = "AKIAIOSFODNN7EXAMPLE"'
REAL_FILE = f"import os\n\n{SECRET_LINE}\n\n\ndef call():\n    return API_KEY\n"


# --- why kind == "secret" is never auto-appliable -------------------------------------------


def test_read_file_path_redacts_the_secret_literal():
    """dispatch()'s read_file runs redact() with no known lines: surrounding code survives, the
    literal does not. So the agent never sees the bytes it would have to match on."""
    seen = secret_redaction.redact(REAL_FILE)
    assert secret_redaction.PLACEHOLDER in seen
    assert "AKIAIOSFODNN7EXAMPLE" not in seen
    assert "def call():" in seen  # only the literal is gone, not the context
    assert seen.splitlines()[2] != SECRET_LINE


def test_evidence_snippet_path_blanks_every_line():
    """_redacted_snippet passes every line as a known secret line for kind == "secret"."""
    snippet = f"{SECRET_LINE}\n"
    blanked = secret_redaction.redact(snippet, {1})
    assert blanked.strip() == secret_redaction.PLACEHOLDER


def test_patch_spanning_a_redacted_secret_cannot_apply(tmp_path):
    """The payoff. A secret fix must replace the literal, so its original_code necessarily spans
    the redacted region -- and that string does not occur in the real file. _apply_patch rejects
    it as 'source changed', which is a confusing dead end for a reviewer. Triage should catch
    this before an LLM call is ever made."""
    (tmp_path / "conf.py").write_text(REAL_FILE, encoding="utf-8")

    # The best original_code the agent could possibly emit, having only ever seen redacted content.
    agent_original = secret_redaction.redact(REAL_FILE).splitlines()[2]
    assert secret_redaction.PLACEHOLDER in agent_original

    with pytest.raises(_ManualReview) as exc:
        _apply_patch(str(tmp_path), "conf.py", agent_original, 'API_KEY = os.environ["API_KEY"]')
    assert "Source changed" in str(exc.value)


def test_patch_not_spanning_the_secret_still_applies(tmp_path):
    """Scoping the claim honestly: redaction only blocks patches that span the literal. A patch
    elsewhere in the same file is unaffected -- which is why the rule keys on kind == "secret"
    (where replacing the literal IS the fix), not on "the file contains a secret"."""
    (tmp_path / "conf.py").write_text(REAL_FILE, encoding="utf-8")
    _apply_patch(str(tmp_path), "conf.py", "    return API_KEY", "    return API_KEY.strip()")
    assert "API_KEY.strip()" in (tmp_path / "conf.py").read_text(encoding="utf-8")
    assert "AKIAIOSFODNN7EXAMPLE" in (tmp_path / "conf.py").read_text(encoding="utf-8")


# --- triage rules ---------------------------------------------------------------------------


def _f(file="app/main.py", kind="sast", dependency=None):
    return Finding(
        scan_id="s", project_id="p", message="m", kind=kind,
        location=LocationEmbedded(file=file, start_line=3), dependency=dependency,
    )


def test_ordinary_sast_finding_is_eligible(client):
    r = triage(_f())
    assert r.eligible is True
    assert r.strategy == "code-patch"
    assert r.reason is None


def test_missing_file_is_ineligible(client):
    r = triage(_f(file="   "))
    assert (r.eligible, r.strategy) == (False, "none")
    assert "nothing to patch" in r.reason


@pytest.mark.parametrize(
    "path", ["node_modules/lodash/index.js", "vendor/pkg/a.go", "app/dist/bundle.py", ".venv/lib/x.py"]
)
def test_vendored_and_build_paths_are_ineligible(client, path):
    r = triage(_f(file=path))
    assert (r.eligible, r.strategy) == (False, "none")
    assert "overwritten" in r.reason


@pytest.mark.parametrize(
    "path", ["static/app.min.js", "static/app.js.map", "package-lock.json", "sub/yarn.lock"]
)
def test_generated_artifacts_are_ineligible(client, path):
    r = triage(_f(file=path))
    assert (r.eligible, r.strategy) == (False, "none")
    assert "generated or minified" in r.reason


@pytest.mark.parametrize("path", ["assets/logo.png", "lib/native.so", "docs/spec.pdf"])
def test_binary_files_are_ineligible(client, path):
    r = triage(_f(file=path))
    assert (r.eligible, r.strategy) == (False, "none")
    assert "binary" in r.reason


def test_secret_finding_routes_to_rotation_not_a_patch(client):
    """The rule the tests above justify: no agent run, and the reason tells the reviewer to rotate
    rather than leaving them with an unexplained apply failure."""
    r = triage(_f(file="config.py", kind="secret"))
    assert (r.eligible, r.strategy) == (False, "rotate-secret")
    assert "Rotate" in r.reason
    assert "git history" in r.reason


def test_sca_with_a_fixed_version_is_eligible(client):
    dep = DependencyEmbedded(package="urllib3", fixed_version="2.0.7", manifest="requirements.txt")
    r = triage(_f(file="requirements.txt", kind="sca", dependency=dep))
    assert (r.eligible, r.strategy) == (True, "dependency-bump")


@pytest.mark.parametrize("dep", [None, DependencyEmbedded(package="left-pad", fixed_version="  ")])
def test_sca_without_a_fixed_version_is_ineligible(client, dep):
    r = triage(_f(file="requirements.txt", kind="sca", dependency=dep))
    assert (r.eligible, r.strategy) == (False, "none")
    assert "no safe version" in r.reason


def test_a_lockfile_sca_finding_is_caught_as_generated_before_the_sca_rule(client):
    """Ordering matters: a lockfile is generated output even when it carries a fixed_version, so
    the bump belongs in the manifest. The generated rule must win."""
    dep = DependencyEmbedded(package="lodash", fixed_version="4.17.21", manifest="package.json")
    r = triage(_f(file="package-lock.json", kind="sca", dependency=dep))
    assert (r.eligible, r.strategy) == (False, "none")
    assert "generated or minified" in r.reason
