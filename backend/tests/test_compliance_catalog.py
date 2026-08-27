"""Guards the hand-written control catalog against the two mistakes that fail silently:
a selector that references a value the scanner never emits (matches nothing, forever) and a
non-assessable control missing its manual_reason (would render an empty rationale)."""

from app.core.compliance_catalog import (
    FINDING_CATEGORIES,
    FINDING_KINDS,
    FRAMEWORK_KEYS_ORDERED,
    FRAMEWORKS,
    SUPPORTED_FRAMEWORK_KEYS,
)
from app.core.owasp import OWASP_CODES_ORDERED


def test_control_ids_are_unique_within_each_framework():
    for key, framework in FRAMEWORKS.items():
        ids = [c.id for c in framework.controls]
        assert len(ids) == len(set(ids)), f"duplicate control id in {key}: {ids}"


def test_manual_controls_carry_a_reason_and_assessable_ones_do_not_need_one():
    for key, framework in FRAMEWORKS.items():
        for control in framework.controls:
            if control.selector is None:
                assert control.manual_reason, f"{key}/{control.id} has no manual_reason"
            else:
                assert control.manual_reason is None, (
                    f"{key}/{control.id} has both a selector and a manual_reason"
                )


def test_selectors_only_reference_values_the_scanner_actually_emits():
    """A typo here (e.g. "secrets" for "secret") would make a control silently pass forever."""
    for key, framework in FRAMEWORKS.items():
        for control in framework.controls:
            if control.selector is None:
                continue
            where = f"{key}/{control.id}"
            assert control.selector.kinds <= FINDING_KINDS, f"{where}: unknown kind"
            assert control.selector.categories <= FINDING_CATEGORIES, f"{where}: unknown category"
            assert set(control.selector.owasp) <= set(OWASP_CODES_ORDERED), f"{where}: unknown OWASP code"


def test_every_selector_constrains_on_something():
    """An all-empty selector matches nothing under union semantics — almost certainly a mistake."""
    for key, framework in FRAMEWORKS.items():
        for control in framework.controls:
            s = control.selector
            if s is None:
                continue
            assert s.kinds or s.categories or s.owasp or s.cwe, f"{key}/{control.id} selects nothing"


def test_fail_severities_are_real_severity_values():
    valid = {"critical", "high", "medium", "low", "info"}
    for key, framework in FRAMEWORKS.items():
        for control in framework.controls:
            assert control.fail_severities <= valid, f"{key}/{control.id}: bad fail_severities"


def test_every_framework_has_both_assessable_and_manual_controls():
    """Assessable: otherwise the framework produces no signal. Manual: every one of these
    standards has process controls, and hiding them would overstate coverage."""
    for key, framework in FRAMEWORKS.items():
        assessable = [c for c in framework.controls if c.selector is not None]
        manual = [c for c in framework.controls if c.selector is None]
        assert assessable, f"{key} has no code-assessable controls"
        assert manual, f"{key} claims every control is code-assessable"
        assert framework.scope_note, f"{key} has no scope_note"


def test_secret_and_dependency_evidence_is_reachable_in_every_framework():
    """The scanner leaves owasp/cwe EMPTY on kind=secret and kind=sca findings. If a framework
    only ever selects on owasp codes, hardcoded credentials and vulnerable dependencies become
    invisible to it — the single most likely silent failure in this catalog."""
    for key, framework in FRAMEWORKS.items():
        kinds = set()
        for control in framework.controls:
            if control.selector is not None:
                kinds |= control.selector.kinds
        assert "secret" in kinds, f"{key} has no control selecting kind=secret"
        assert "sca" in kinds, f"{key} has no control selecting kind=sca"


def test_framework_key_order_lists_exactly_the_supported_frameworks():
    """The wizard is driven by this order, so it must never offer an unreviewed framework --
    and every offered key must still resolve in FRAMEWORKS."""
    assert set(FRAMEWORK_KEYS_ORDERED) == set(SUPPORTED_FRAMEWORK_KEYS)
    assert len(FRAMEWORK_KEYS_ORDERED) == len(SUPPORTED_FRAMEWORK_KEYS)
    assert SUPPORTED_FRAMEWORK_KEYS <= set(FRAMEWORKS)
    # The scope the product commits to today. Widening it is a deliberate edit here too.
    assert SUPPORTED_FRAMEWORK_KEYS == {"soc2", "iso27001"}
