"""Static registry of compliance frameworks and their controls, plus the selectors that
bind each control to the scanner evidence that can speak to it.

A taxonomy table, like app.core.owasp -- deliberately code, not a Mongo collection and not
YAML: there is no CRUD story for controls (nobody edits a framework at runtime), the data
is small, and keeping it in Python makes the selectors type-checked and unit-testable.
Adding a framework = adding one entry to FRAMEWORKS.

Two things to know before editing:

1. **Control titles here are our own one-line paraphrases, never the verbatim text of the
   standard.** ISO/IEC 27001 and the SOC 2 Trust Services Criteria are copyrighted; we
   reference the official identifier (`Control.reference`) and describe the intent in our
   own words. Do not paste standard text in.

2. **Selectors must not key off `owasp` alone.** The Go scanner only populates `owasp`/`cwe`
   on kind="sast" and kind="config" findings. kind="secret" arrives with category="secret"
   and *empty* owasp/cwe; kind="sca" arrives with category="dependency", empty owasp/cwe,
   and its CVE/GHSA ids in `dependency.advisory_ids`. A control mapped only on OWASP codes
   would silently ignore every hardcoded-credential and vulnerable-dependency finding --
   exactly the evidence these frameworks care most about. tests/test_compliance_catalog.py
   asserts every selector value is a real scanner value, which catches typos that would
   otherwise match nothing forever.

A control with `selector=None` is one no code scanner can evidence (governance, HR, vendor
management, incident-response process). Those are reported as `needs_manual_review` with
`manual_reason` as the rationale -- never as a pass.
"""

from dataclasses import dataclass, field

# Scanner vocabularies the selectors below are allowed to reference. Kept here (rather than
# imported from models.finding) so the catalog test can assert against a single source and
# so a scanner-side rename shows up as a failing test instead of a dead selector.
FINDING_KINDS: frozenset[str] = frozenset({"sast", "secret", "sca", "config"})

# Categories the Go scanner's rule corpus actually emits (internal/rules/data/**/*.yaml),
# plus the two hardcoded in internal/findings/builder.go for secret and dependency findings.
FINDING_CATEGORIES: frozenset[str] = frozenset(
    {
        "authentication",
        "command-injection",
        "cryptography",
        "dangerous-functions",
        "dangerous-patterns",
        "dependency",
        "deserialization",
        "error-handling",
        "format-string",
        "injection",
        "insecure-transport",
        "logging",
        "misconfiguration",
        "open-redirect",
        "path-traversal",
        "race-condition",
        "redos",
        "secret",
        "security-misconfiguration",
        "sensitive-data",
        "ssrf",
        "ssti",
        "supply-chain",
        "xss",
        "xxe",
    }
)

# The default bar for "this control fails". Medium/low matches downgrade a control to
# `partial` instead -- see compliance_audit_service.evaluate.
DEFAULT_FAIL_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})


@dataclass(frozen=True)
class ControlSelector:
    """Which findings count as evidence against a control.

    A finding matches if it satisfies ANY populated field (union, not intersection): an
    empty field is "no constraint", not "matches nothing". So
    ControlSelector(kinds={"secret"}, categories={"cryptography"}) matches every secret
    finding *and* every cryptography finding.
    """

    kinds: frozenset[str] = frozenset()
    categories: frozenset[str] = frozenset()
    owasp: frozenset[str] = frozenset()
    cwe: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Control:
    id: str
    title: str  # our paraphrase of the control's intent -- NOT the standard's wording
    reference: str  # the official identifier, for traceability back to the standard
    selector: ControlSelector | None  # None => not evidenceable from source code
    manual_reason: str | None = None  # required iff selector is None
    fail_severities: frozenset[str] = DEFAULT_FAIL_SEVERITIES


@dataclass(frozen=True)
class Framework:
    key: str
    title: str
    # Shown above the control table so nobody mistakes the scope of what was assessed.
    scope_note: str
    controls: list[Control] = field(default_factory=list)


def _manual(id_: str, title: str, reference: str, reason: str) -> Control:
    return Control(id_, title, reference, None, manual_reason=reason)


# Reused selector shapes. Named so the same evidence class reads identically across
# frameworks -- and so a scanner category rename is a one-line fix here.
_SECRETS = ControlSelector(kinds=frozenset({"secret"}))
_DEPENDENCIES = ControlSelector(kinds=frozenset({"sca"}), owasp=frozenset({"A06:2025"}))
_CRYPTO = ControlSelector(
    categories=frozenset({"cryptography", "insecure-transport"}), owasp=frozenset({"A02:2025"})
)
_ACCESS_CONTROL = ControlSelector(
    categories=frozenset({"authentication", "path-traversal", "open-redirect"}),
    owasp=frozenset({"A01:2025", "A07:2025"}),
)
_INJECTION = ControlSelector(
    categories=frozenset(
        {"injection", "command-injection", "xss", "ssti", "xxe", "deserialization", "format-string"}
    ),
    owasp=frozenset({"A03:2025"}),
)
_MISCONFIG = ControlSelector(
    categories=frozenset({"security-misconfiguration", "misconfiguration"}),
    owasp=frozenset({"A05:2025"}),
)
_LOGGING = ControlSelector(
    categories=frozenset({"logging", "error-handling"}), owasp=frozenset({"A09:2025"})
)
_SSRF = ControlSelector(categories=frozenset({"ssrf"}), owasp=frozenset({"A10:2025"}))
_INTEGRITY = ControlSelector(
    categories=frozenset({"supply-chain", "deserialization"}), owasp=frozenset({"A08:2025"})
)
_SENSITIVE_DATA = ControlSelector(
    categories=frozenset({"sensitive-data"}), owasp=frozenset({"A02:2025"})
)
_SECURE_DESIGN = ControlSelector(
    categories=frozenset({"dangerous-functions", "dangerous-patterns", "race-condition", "redos"}),
    owasp=frozenset({"A04:2025"}),
)

# A secret committed to source is a finding at any severity -- there is no "acceptable" one.
_ANY_SEVERITY = frozenset({"critical", "high", "medium", "low", "info"})


SOC2 = Framework(
    key="soc2",
    title="SOC 2 (Trust Services Criteria)",
    scope_note=(
        "Only the Common Criteria that source code can evidence are assessed here -- primarily "
        "CC6 (logical access) and CC7 (system operations). CC1-CC5 and CC8-CC9 are governance, "
        "risk-assessment and vendor controls that require documentation and management attestation."
    ),
    controls=[
        Control(
            "CC6.1",
            "Logical access to systems and data is restricted to authorised users",
            "SOC 2 TSC CC6.1",
            _ACCESS_CONTROL,
        ),
        Control(
            "CC6.6",
            "Credentials and keys are not embedded in source code or configuration",
            "SOC 2 TSC CC6.6",
            _SECRETS,
            fail_severities=_ANY_SEVERITY,
        ),
        Control(
            "CC6.7",
            "Data in transit is protected by strong transport encryption",
            "SOC 2 TSC CC6.7",
            _CRYPTO,
        ),
        Control(
            "CC6.8",
            "Unauthorised or malicious software is prevented from being introduced",
            "SOC 2 TSC CC6.8",
            _INTEGRITY,
        ),
        Control(
            "CC7.1",
            "Configuration is monitored for deviations from a secure baseline",
            "SOC 2 TSC CC7.1",
            _MISCONFIG,
        ),
        Control(
            "CC7.2",
            "Security events are logged and anomalies are detectable",
            "SOC 2 TSC CC7.2",
            _LOGGING,
        ),
        Control(
            "CC7.3",
            "Known vulnerabilities in third-party components are identified and remediated",
            "SOC 2 TSC CC7.3",
            _DEPENDENCIES,
        ),
        Control(
            "CC8.1",
            "Changes are developed against secure coding practices before release",
            "SOC 2 TSC CC8.1",
            _INJECTION,
        ),
        Control(
            "CC6.3",
            "Server-side request handling does not allow access to internal resources",
            "SOC 2 TSC CC6.3",
            _SSRF,
        ),
        Control(
            "CC3.2",
            "Design-level security risks are identified and addressed",
            "SOC 2 TSC CC3.2",
            _SECURE_DESIGN,
        ),
        _manual(
            "CC1.1",
            "The organisation demonstrates a commitment to integrity and ethical values",
            "SOC 2 TSC CC1.1",
            "Governance control. Evidence it with your code of conduct, ethics policy and "
            "board-level oversight records -- not derivable from source code.",
        ),
        _manual(
            "CC1.4",
            "Personnel are competent and security responsibilities are assigned",
            "SOC 2 TSC CC1.4",
            "HR control. Evidence it with role descriptions, background-check records and "
            "security training completion.",
        ),
        _manual(
            "CC2.1",
            "Quality information is used to support the functioning of internal control",
            "SOC 2 TSC CC2.1",
            "Process control. Evidence it with your monitoring dashboards, metrics reviews and "
            "management reporting cadence.",
        ),
        _manual(
            "CC4.1",
            "Controls are evaluated on an ongoing basis",
            "SOC 2 TSC CC4.1",
            "Process control. Evidence it with internal audit reports and control self-assessments.",
        ),
        _manual(
            "CC5.2",
            "Technology general controls are selected and developed",
            "SOC 2 TSC CC5.2",
            "Process control. Evidence it with your change-management and access-review procedures.",
        ),
        _manual(
            "CC7.4",
            "Security incidents are responded to according to a defined process",
            "SOC 2 TSC CC7.4",
            "Process control. Evidence it with your incident-response plan, on-call rota and "
            "post-incident reviews.",
        ),
        _manual(
            "CC7.5",
            "The organisation recovers from identified security incidents",
            "SOC 2 TSC CC7.5",
            "Process control. Evidence it with recovery runbooks and tested backup restoration.",
        ),
        _manual(
            "CC9.2",
            "Risks associated with vendors and business partners are assessed and managed",
            "SOC 2 TSC CC9.2",
            "Vendor-management control. Evidence it with your third-party risk assessments and "
            "signed data-processing agreements.",
        ),
    ],
)


ISO27001 = Framework(
    key="iso27001",
    title="ISO/IEC 27001:2022 (Annex A)",
    scope_note=(
        "A subset of Annex A -- the technological controls in A.8 that source code can evidence. "
        "The organisational (A.5), people (A.6) and physical (A.7) controls, and the ISMS clauses "
        "4-10, are outside what a code scanner can observe."
    ),
    controls=[
        Control(
            "A.8.24",
            "Cryptography is used correctly and with approved algorithms",
            "ISO/IEC 27001:2022 A.8.24",
            _CRYPTO,
        ),
        Control(
            "A.8.28",
            "Software is developed following secure coding principles",
            "ISO/IEC 27001:2022 A.8.28",
            _INJECTION,
        ),
        Control(
            "A.8.8",
            "Technical vulnerabilities in use are identified and managed",
            "ISO/IEC 27001:2022 A.8.8",
            _DEPENDENCIES,
        ),
        Control(
            "A.8.9",
            "Configurations of systems are established and maintained securely",
            "ISO/IEC 27001:2022 A.8.9",
            _MISCONFIG,
        ),
        Control(
            "A.8.3",
            "Access to information and application functions is restricted",
            "ISO/IEC 27001:2022 A.8.3",
            _ACCESS_CONTROL,
        ),
        Control(
            "A.8.5",
            "Authentication is implemented securely",
            "ISO/IEC 27001:2022 A.8.5",
            ControlSelector(
                categories=frozenset({"authentication"}), owasp=frozenset({"A07:2025"})
            ),
        ),
        Control(
            "A.8.12",
            "Secrets and sensitive data are protected against leakage",
            "ISO/IEC 27001:2022 A.8.12",
            ControlSelector(kinds=frozenset({"secret"}), categories=frozenset({"sensitive-data"})),
            fail_severities=_ANY_SEVERITY,
        ),
        Control(
            "A.8.15",
            "Logs recording relevant events are produced and protected",
            "ISO/IEC 27001:2022 A.8.15",
            _LOGGING,
        ),
        Control(
            "A.8.25",
            "Security is designed into the development lifecycle",
            "ISO/IEC 27001:2022 A.8.25",
            _SECURE_DESIGN,
        ),
        Control(
            "A.8.26",
            "Security requirements of application services are identified and met",
            "ISO/IEC 27001:2022 A.8.26",
            _SSRF,
        ),
        Control(
            "A.8.30",
            "Outsourced and third-party components are supervised and verified",
            "ISO/IEC 27001:2022 A.8.30",
            _INTEGRITY,
        ),
        _manual(
            "A.5.1",
            "Information security policies are defined and approved by management",
            "ISO/IEC 27001:2022 A.5.1",
            "Organisational control. Evidence it with your approved information security policy set.",
        ),
        _manual(
            "A.5.15",
            "Access control rules are established based on business requirements",
            "ISO/IEC 27001:2022 A.5.15",
            "Organisational control. Evidence it with your access control policy and periodic "
            "access reviews -- the code shows enforcement, not the rules or the review.",
        ),
        _manual(
            "A.5.24",
            "Incident management planning and preparation is in place",
            "ISO/IEC 27001:2022 A.5.24",
            "Process control. Evidence it with your incident response plan and exercise records.",
        ),
        _manual(
            "A.6.3",
            "Personnel receive information security awareness and training",
            "ISO/IEC 27001:2022 A.6.3",
            "People control. Evidence it with training records and completion rates.",
        ),
        _manual(
            "A.5.19",
            "Information security in supplier relationships is managed",
            "ISO/IEC 27001:2022 A.5.19",
            "Vendor-management control. Evidence it with supplier security agreements and reviews.",
        ),
    ],
)


GDPR = Framework(
    key="gdpr",
    title="GDPR (technical measures)",
    scope_note=(
        "GDPR is a legal regime, not a technical checklist. Only the technical measures under "
        "Art. 25 and Art. 32 can be partially evidenced from source code. Lawful basis, data "
        "subject rights, records of processing, DPIAs, transfers and breach notification are legal "
        "and procedural obligations -- this audit cannot assess them and does not attempt to."
    ),
    controls=[
        Control(
            "Art.32(1)(a)",
            "Personal data is encrypted, in transit and at rest",
            "GDPR Art. 32(1)(a)",
            _CRYPTO,
        ),
        Control(
            "Art.32(1)(b)-conf",
            "Confidentiality of processing systems is ensured by access controls",
            "GDPR Art. 32(1)(b)",
            _ACCESS_CONTROL,
        ),
        Control(
            "Art.32(1)(b)-int",
            "Integrity of processing systems is protected against injection and tampering",
            "GDPR Art. 32(1)(b)",
            _INJECTION,
        ),
        Control(
            "Art.32(1)(b)-res",
            "Processing systems are resilient and securely configured",
            "GDPR Art. 32(1)(b)",
            _MISCONFIG,
        ),
        Control(
            "Art.32(1)(d)",
            "Security of processing is regularly tested and known weaknesses are remediated",
            "GDPR Art. 32(1)(d)",
            _DEPENDENCIES,
        ),
        Control(
            "Art.25(1)",
            "Data protection by design is reflected in how the software is built",
            "GDPR Art. 25(1)",
            _SECURE_DESIGN,
        ),
        Control(
            "Art.5(1)(f)",
            "Personal data is protected against unauthorised disclosure -- no credentials or "
            "personal data in source",
            "GDPR Art. 5(1)(f)",
            ControlSelector(kinds=frozenset({"secret"}), categories=frozenset({"sensitive-data"})),
            fail_severities=_ANY_SEVERITY,
        ),
        Control(
            "Art.33-detect",
            "Breaches are detectable -- security-relevant events are logged",
            "GDPR Art. 33",
            _LOGGING,
        ),
        _manual(
            "Art.6",
            "Processing has a valid lawful basis",
            "GDPR Art. 6",
            "Legal determination. Requires your record of processing activities and legal review -- "
            "no code scanner can establish a lawful basis.",
        ),
        _manual(
            "Art.30",
            "Records of processing activities are maintained",
            "GDPR Art. 30",
            "Documentation obligation. Evidence it with your Article 30 record.",
        ),
        _manual(
            "Art.33-notify",
            "Personal data breaches are notified to the supervisory authority within 72 hours",
            "GDPR Art. 33",
            "Process obligation. Evidence it with your breach notification procedure and register.",
        ),
        _manual(
            "Art.35",
            "A data protection impact assessment is carried out for high-risk processing",
            "GDPR Art. 35",
            "Assessment obligation. Evidence it with completed DPIAs.",
        ),
        _manual(
            "Art.15-22",
            "Data subject rights can be exercised (access, erasure, portability, objection)",
            "GDPR Art. 15-22",
            "Process obligation. Evidence it with your data subject request workflow and SLA -- "
            "the presence of an endpoint is not evidence the right is honoured.",
        ),
        _manual(
            "Art.28",
            "Processors are engaged under a written data processing agreement",
            "GDPR Art. 28",
            "Contractual obligation. Evidence it with signed DPAs for every processor.",
        ),
    ],
)


HIPAA = Framework(
    key="hipaa",
    title="HIPAA Security Rule (technical safeguards)",
    scope_note=(
        "Only the technical safeguards at 45 CFR 164.312 -- and only their software-observable "
        "aspects -- are assessed. The administrative safeguards (164.308) and physical safeguards "
        "(164.310) are organisational and cannot be evidenced from source code. This audit makes no "
        "determination about whether the system in fact handles PHI."
    ),
    controls=[
        Control(
            "164.312(a)(1)",
            "Access control: only authorised users and programs can reach ePHI",
            "45 CFR 164.312(a)(1)",
            _ACCESS_CONTROL,
        ),
        Control(
            "164.312(a)(2)(iv)",
            "Encryption and decryption of ePHI at rest uses sound cryptography",
            "45 CFR 164.312(a)(2)(iv)",
            _CRYPTO,
        ),
        Control(
            "164.312(b)",
            "Audit controls record activity in systems containing ePHI",
            "45 CFR 164.312(b)",
            _LOGGING,
        ),
        Control(
            "164.312(c)(1)",
            "ePHI is protected from improper alteration or destruction",
            "45 CFR 164.312(c)(1)",
            _INJECTION,
        ),
        Control(
            "164.312(d)",
            "Person or entity authentication is implemented securely",
            "45 CFR 164.312(d)",
            ControlSelector(
                categories=frozenset({"authentication"}), owasp=frozenset({"A07:2025"})
            ),
        ),
        Control(
            "164.312(e)(1)",
            "Transmission security guards ePHI against interception over networks",
            "45 CFR 164.312(e)(1)",
            ControlSelector(
                categories=frozenset({"insecure-transport", "ssrf"}),
                owasp=frozenset({"A02:2025", "A10:2025"}),
            ),
        ),
        Control(
            "164.308(a)(1)(ii)(B)-tech",
            "Identified technical vulnerabilities are reduced to a reasonable level",
            "45 CFR 164.308(a)(1)(ii)(B)",
            _DEPENDENCIES,
        ),
        Control(
            "164.308(a)(5)(ii)(D)-tech",
            "Passwords and keys are managed -- not hardcoded into software",
            "45 CFR 164.308(a)(5)(ii)(D)",
            _SECRETS,
            fail_severities=_ANY_SEVERITY,
        ),
        Control(
            "164.312-config",
            "Systems handling ePHI are securely configured",
            "45 CFR 164.312",
            _MISCONFIG,
        ),
        _manual(
            "164.308(a)(1)(ii)(A)",
            "A risk analysis of ePHI confidentiality, integrity and availability is conducted",
            "45 CFR 164.308(a)(1)(ii)(A)",
            "Administrative safeguard. Evidence it with your documented security risk analysis.",
        ),
        _manual(
            "164.308(a)(3)",
            "Workforce security: authorisation and supervision of workforce members",
            "45 CFR 164.308(a)(3)",
            "Administrative safeguard. Evidence it with role authorisation records and termination "
            "procedures.",
        ),
        _manual(
            "164.308(a)(4)",
            "Information access management: policies for granting access to ePHI",
            "45 CFR 164.308(a)(4)",
            "Administrative safeguard. Evidence it with your access authorisation policy and "
            "periodic access reviews.",
        ),
        _manual(
            "164.308(a)(6)",
            "Security incident procedures are documented and followed",
            "45 CFR 164.308(a)(6)",
            "Administrative safeguard. Evidence it with your incident response procedure and log.",
        ),
        _manual(
            "164.308(a)(7)",
            "Contingency plan: data backup, disaster recovery and emergency mode operation",
            "45 CFR 164.308(a)(7)",
            "Administrative safeguard. Evidence it with tested backup and disaster recovery plans.",
        ),
        _manual(
            "164.308(b)(1)",
            "Business associate contracts are in place before ePHI is disclosed",
            "45 CFR 164.308(b)(1)",
            "Contractual obligation. Evidence it with executed business associate agreements.",
        ),
        _manual(
            "164.310",
            "Physical safeguards protect facilities and workstations holding ePHI",
            "45 CFR 164.310",
            "Physical safeguard. Evidence it with facility access controls and device inventory.",
        ),
    ],
)


FRAMEWORKS: dict[str, Framework] = {f.key: f for f in (SOC2, ISO27001, GDPR, HIPAA)}

# Stable order for the wizard and the results view.
FRAMEWORK_KEYS_ORDERED: list[str] = list(FRAMEWORKS)


def get_framework(key: str) -> Framework | None:
    return FRAMEWORKS.get(key)
