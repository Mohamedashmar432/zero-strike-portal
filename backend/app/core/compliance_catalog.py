"""Static registry of compliance frameworks and their controls, plus the selectors that
bind each control to the scanner evidence that can speak to it.

A taxonomy table, like app.core.owasp -- deliberately code, not a Mongo collection and not
YAML: there is no CRUD story for controls (nobody edits a framework at runtime), the data
is small, and keeping it in Python makes the selectors type-checked and unit-testable.
Adding a framework = adding one entry to FRAMEWORKS.

Two things to know before editing:

1. **Control titles here are our own one-line paraphrases, never the verbatim text of the
   standard.** ISO/IEC 27001, NIST, PCI-DSS, and the SOC 2 Trust Services Criteria are copyrighted;
   we reference the official identifier (`Control.reference`) and describe the intent in our
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
    domain: str = "General Controls"
    description: str = ""
    recommendation: str = ""


@dataclass(frozen=True)
class Framework:
    key: str
    title: str
    # Shown above the control table so nobody mistakes the scope of what was assessed.
    scope_note: str
    controls: list[Control] = field(default_factory=list)


def _manual(
    id_: str,
    title: str,
    reference: str,
    reason: str,
    domain: str = "Governance & Process",
    description: str = "",
    recommendation: str = "",
) -> Control:
    return Control(
        id=id_,
        title=title,
        reference=reference,
        selector=None,
        manual_reason=reason,
        domain=domain,
        description=description or reason,
        recommendation=recommendation
        or "Provide verifiable organizational documentation, signed attestations, or policy registers.",
    )


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
            domain="CC6: Logical & Physical Access Controls",
            description="Restricts logical access to software components, internal APIs, and datasets to authenticated entities with least privilege.",
            recommendation="Implement centralized authentication guards, validate authorization on all routes, and sanitize file path inputs to prevent traversal.",
        ),
        Control(
            "CC6.6",
            "Credentials and keys are not embedded in source code or configuration",
            "SOC 2 TSC CC6.6",
            _SECRETS,
            fail_severities=_ANY_SEVERITY,
            domain="CC6: Logical & Physical Access Controls",
            description="Requires credentials, API keys, tokens, and private keys to be stored in secure secrets managers rather than source repositories.",
            recommendation="Revoke and rotate exposed credentials immediately. Store secrets in environment variables or key vaults (e.g. HashiCorp Vault, AWS Secrets Manager).",
        ),
        Control(
            "CC6.7",
            "Data in transit is protected by strong transport encryption",
            "SOC 2 TSC CC6.7",
            _CRYPTO,
            domain="CC6: Logical & Physical Access Controls",
            description="Protects data transmitted across internal and external networks using robust cryptographic protocols (TLS 1.2+) and cipher suites.",
            recommendation="Enforce HTTPS/TLS on all endpoints, disable obsolete protocols (SSLv3/TLS 1.0/1.1), and avoid weak cryptographic primitives like MD5 or DES.",
        ),
        Control(
            "CC6.8",
            "Unauthorised or malicious software is prevented from being introduced",
            "SOC 2 TSC CC6.8",
            _INTEGRITY,
            domain="CC6: Logical & Physical Access Controls",
            description="Mitigates risk of supply chain tampering, unauthorized package injection, and insecure object deserialization.",
            recommendation="Lock dependency hashes, use safe deserialization parsers, and pin build artifacts to trusted registries.",
        ),
        Control(
            "CC6.3",
            "Server-side request handling does not allow access to internal resources",
            "SOC 2 TSC CC6.3",
            _SSRF,
            domain="CC6: Logical & Physical Access Controls",
            description="Ensures outbound HTTP clients and webhooks cannot be manipulated into probing private internal networks or metadata endpoints.",
            recommendation="Validate destination URLs against strict domain allowlists and block loopback (127.0.0.1) and link-local (169.254.169.254) addresses.",
        ),
        Control(
            "CC7.1",
            "Configuration is monitored for deviations from a secure baseline",
            "SOC 2 TSC CC7.1",
            _MISCONFIG,
            domain="CC7: System Operations & Monitoring",
            description="Validates application, container, and framework configurations against hardened security baselines.",
            recommendation="Disable debug modes in production, configure secure CORS and CSP headers, and enforce strict cookie attributes (Secure; HttpOnly; SameSite).",
        ),
        Control(
            "CC7.2",
            "Security events are logged and anomalies are detectable",
            "SOC 2 TSC CC7.2",
            _LOGGING,
            domain="CC7: System Operations & Monitoring",
            description="Captures security-relevant application events, access failures, and exceptions to enable detection and audit trails.",
            recommendation="Ensure robust structured logging for auth events, sanitize sensitive PII from logs, and prevent unhandled exception leakage.",
        ),
        Control(
            "CC7.3",
            "Known vulnerabilities in third-party components are identified and remediated",
            "SOC 2 TSC CC7.3",
            _DEPENDENCIES,
            domain="CC7: System Operations & Monitoring",
            description="Continuously scans third-party open source packages for published CVEs and upgrades vulnerable libraries.",
            recommendation="Upgrade flagged packages to patched versions or apply vendor-recommended mitigations.",
        ),
        Control(
            "CC8.1",
            "Changes are developed against secure coding practices before release",
            "SOC 2 TSC CC8.1",
            _INJECTION,
            domain="CC8: Change Management & Secure SDLC",
            description="Requires input validation and parameterized queries to eliminate injection flaws (SQLi, XSS, Command Injection) prior to deployment.",
            recommendation="Use parameterized SQL queries / ORMs, context-aware HTML escaping, and strict schema validation on all user inputs.",
        ),
        Control(
            "CC3.2",
            "Design-level security risks are identified and addressed",
            "SOC 2 TSC CC3.2",
            _SECURE_DESIGN,
            domain="CC3: Risk Assessment & Architecture",
            description="Identifies architecture risks, dangerous function calls, concurrency race conditions, and algorithmic denial-of-service patterns.",
            recommendation="Refactor risky patterns, avoid dangerous functions (e.g. eval, system), and implement timeout bounds on regular expressions.",
        ),
        _manual(
            "CC1.1",
            "The organisation demonstrates a commitment to integrity and ethical values",
            "SOC 2 TSC CC1.1",
            "Governance control. Evidence it with your code of conduct, ethics policy and board-level oversight records -- not derivable from source code.",
            domain="CC1: Control Environment & Governance",
        ),
        _manual(
            "CC1.4",
            "Personnel are competent and security responsibilities are assigned",
            "SOC 2 TSC CC1.4",
            "HR control. Evidence it with role descriptions, background-check records and security training completion.",
            domain="CC1: Control Environment & Governance",
        ),
        _manual(
            "CC2.1",
            "Quality information is used to support the functioning of internal control",
            "SOC 2 TSC CC2.1",
            "Process control. Evidence it with your monitoring dashboards, metrics reviews and management reporting cadence.",
            domain="CC2: Communication & Information",
        ),
        _manual(
            "CC4.1",
            "Controls are evaluated on an ongoing basis",
            "SOC 2 TSC CC4.1",
            "Process control. Evidence it with internal audit reports and control self-assessments.",
            domain="CC4: Monitoring Activities",
        ),
        _manual(
            "CC5.2",
            "Technology general controls are selected and developed",
            "SOC 2 TSC CC5.2",
            "Process control. Evidence it with your change-management and access-review procedures.",
            domain="CC5: Control Activities",
        ),
        _manual(
            "CC7.4",
            "Security incidents are responded to according to a defined process",
            "SOC 2 TSC CC7.4",
            "Process control. Evidence it with your incident-response plan, on-call rota and post-incident reviews.",
            domain="CC7: System Operations & Monitoring",
        ),
        _manual(
            "CC7.5",
            "The organisation recovers from identified security incidents",
            "SOC 2 TSC CC7.5",
            "Process control. Evidence it with recovery runbooks and tested backup restoration.",
            domain="CC7: System Operations & Monitoring",
        ),
        _manual(
            "CC9.2",
            "Risks associated with vendors and business partners are assessed and managed",
            "SOC 2 TSC CC9.2",
            "Vendor-management control. Evidence it with your third-party risk assessments and signed data-processing agreements.",
            domain="CC9: Vendor Risk Management",
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
            domain="A.8: Technological Controls",
            description="Enforces standardized cryptography, secure cipher suites, and authenticated encryption for sensitive data handling.",
            recommendation="Use industry-standard libraries (e.g. AES-GCM, RSA-OAEP, SHA-256) and avoid proprietary or deprecated algorithms.",
        ),
        Control(
            "A.8.28",
            "Software is developed following secure coding principles",
            "ISO/IEC 27001:2022 A.8.28",
            _INJECTION,
            domain="A.8: Technological Controls",
            description="Applies secure coding practices across the software engineering lifecycle to prevent injection, tampering, and buffer issues.",
            recommendation="Enforce automated linting, parameterization, and context-sensitive output encoding across all codebases.",
        ),
        Control(
            "A.8.8",
            "Technical vulnerabilities in use are identified and managed",
            "ISO/IEC 27001:2022 A.8.8",
            _DEPENDENCIES,
            domain="A.8: Technological Controls",
            description="Maintains awareness of third-party software vulnerabilities and ensures timely patching according to risk severity.",
            recommendation="Establish automated dependency scanning in CI/CD and update vulnerable libraries to supported releases.",
        ),
        Control(
            "A.8.9",
            "Configurations of systems are established and maintained securely",
            "ISO/IEC 27001:2022 A.8.9",
            _MISCONFIG,
            domain="A.8: Technological Controls",
            description="Hardens application settings, disabling unnecessary features, default credentials, and verbose error displays.",
            recommendation="Adopt infrastructure-as-code hardening baselines and review application configuration files for security settings.",
        ),
        Control(
            "A.8.3",
            "Access to information and application functions is restricted",
            "ISO/IEC 27001:2022 A.8.3",
            _ACCESS_CONTROL,
            domain="A.8: Technological Controls",
            description="Restricts access to data and application functionality strictly to authorized roles and verified principals.",
            recommendation="Enforce role-based access control (RBAC), prevent path manipulation, and protect against direct object reference vulnerabilities.",
        ),
        Control(
            "A.8.5",
            "Authentication is implemented securely",
            "ISO/IEC 27001:2022 A.8.5",
            ControlSelector(
                categories=frozenset({"authentication"}), owasp=frozenset({"A07:2025"})
            ),
            domain="A.8: Technological Controls",
            description="Validates that authentication tokens, session lifetimes, password hashing, and login handlers adhere to secure standards.",
            recommendation="Use strong hashing (Argon2id, bcrypt), implement rate limiting on login endpoints, and secure session cookies.",
        ),
        Control(
            "A.8.12",
            "Secrets and sensitive data are protected against leakage",
            "ISO/IEC 27001:2022 A.8.12",
            ControlSelector(kinds=frozenset({"secret"}), categories=frozenset({"sensitive-data"})),
            fail_severities=_ANY_SEVERITY,
            domain="A.8: Technological Controls",
            description="Prevents leakage of sensitive information, PII, API tokens, and credentials in source code or repositories.",
            recommendation="Scan repositories for secrets, sanitize sensitive parameters from logs, and mask PII in transit.",
        ),
        Control(
            "A.8.15",
            "Logs recording relevant events are produced and protected",
            "ISO/IEC 27001:2022 A.8.15",
            _LOGGING,
            domain="A.8: Technological Controls",
            description="Produces comprehensive audit logs for critical operations while protecting log integrity and preventing sensitive data logging.",
            recommendation="Configure audit logging for security events and ensure log streams are forwarded to a tamper-resistant SIEM.",
        ),
        Control(
            "A.8.25",
            "Security is designed into the development lifecycle",
            "ISO/IEC 27001:2022 A.8.25",
            _SECURE_DESIGN,
            domain="A.8: Technological Controls",
            description="Embeds security architecture requirements, threat modeling, and defensive coding patterns into the development lifecycle.",
            recommendation="Conduct threat modeling for major architectural components and replace unsafe native calls with safe abstractions.",
        ),
        Control(
            "A.8.26",
            "Security requirements of application services are identified and met",
            "ISO/IEC 27001:2022 A.8.26",
            _SSRF,
            domain="A.8: Technological Controls",
            description="Guards against application layer risks including SSRF, unauthorized outbound network requests, and external service abuse.",
            recommendation="Validate all remote target URLs with domain allowlists and isolate service outbound networking.",
        ),
        Control(
            "A.8.30",
            "Outsourced and third-party components are supervised and verified",
            "ISO/IEC 27001:2022 A.8.30",
            _INTEGRITY,
            domain="A.8: Technological Controls",
            description="Verifies the integrity and authenticity of software components sourced from third parties and open-source ecosystems.",
            recommendation="Verify checksums/signatures for external libraries and implement package provenance checks in build pipelines.",
        ),
        _manual(
            "A.5.1",
            "Information security policies are defined and approved by management",
            "ISO/IEC 27001:2022 A.5.1",
            "Organisational control. Evidence it with your approved information security policy set.",
            domain="A.5: Organisational Controls",
        ),
        _manual(
            "A.5.15",
            "Access control rules are established based on business requirements",
            "ISO/IEC 27001:2022 A.5.15",
            "Organisational control. Evidence it with your access control policy and periodic access reviews -- the code shows enforcement, not the rules or the review.",
            domain="A.5: Organisational Controls",
        ),
        _manual(
            "A.5.24",
            "Incident management planning and preparation is in place",
            "ISO/IEC 27001:2022 A.5.24",
            "Process control. Evidence it with your incident response plan and exercise records.",
            domain="A.5: Organisational Controls",
        ),
        _manual(
            "A.6.3",
            "Personnel receive information security awareness and training",
            "ISO/IEC 27001:2022 A.6.3",
            "People control. Evidence it with training records and completion rates.",
            domain="A.6: People Controls",
        ),
        _manual(
            "A.5.19",
            "Information security in supplier relationships is managed",
            "ISO/IEC 27001:2022 A.5.19",
            "Vendor-management control. Evidence it with supplier security agreements and reviews.",
            domain="A.5: Organisational Controls",
        ),
    ],
)


GDPR = Framework(
    key="gdpr",
    title="GDPR (Technical Measures)",
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
            domain="Art. 32: Security of Processing",
            description="Applies state-of-the-art encryption algorithms and secure transport channels to protect personal data against interception and theft.",
            recommendation="Use TLS 1.3/1.2 for all external communication and AES-256 for sensitive persistent storage.",
        ),
        Control(
            "Art.32(1)(b)-conf",
            "Confidentiality of processing systems is ensured by access controls",
            "GDPR Art. 32(1)(b)",
            _ACCESS_CONTROL,
            domain="Art. 32: Security of Processing",
            description="Guarantees ongoing confidentiality of personal data by enforcing strict identity authentication and authorization barriers.",
            recommendation="Enforce multi-factor authentication, validate authorization tokens on every endpoint, and prevent parameter tampering.",
        ),
        Control(
            "Art.32(1)(b)-int",
            "Integrity of processing systems is protected against injection and tampering",
            "GDPR Art. 32(1)(b)",
            _INJECTION,
            domain="Art. 32: Security of Processing",
            description="Protects processing pipelines against malicious code injection, data tampering, and command execution vulnerabilities.",
            recommendation="Use parameterized database queries and contextual encoding to guarantee data integrity across processing systems.",
        ),
        Control(
            "Art.32(1)(b)-res",
            "Processing systems are resilient and securely configured",
            "GDPR Art. 32(1)(b)",
            _MISCONFIG,
            domain="Art. 32: Security of Processing",
            description="Ensures processing systems maintain high availability and security hardening against known misconfiguration exploits.",
            recommendation="Harden web server headers, disable default administrative endpoints, and enforce strict CORS configurations.",
        ),
        Control(
            "Art.32(1)(d)",
            "Security of processing is regularly tested and known weaknesses are remediated",
            "GDPR Art. 32(1)(d)",
            _DEPENDENCIES,
            domain="Art. 32: Security of Processing",
            description="Mandates regular vulnerability testing and prompt remediation of insecure third-party software libraries in processing pipelines.",
            recommendation="Integrate automated software composition analysis (SCA) and maintain zero unpatched critical/high vulnerabilities in dependencies.",
        ),
        Control(
            "Art.25(1)",
            "Data protection by design is reflected in how the software is built",
            "GDPR Art. 25(1)",
            _SECURE_DESIGN,
            domain="Art. 25: Data Protection by Design",
            description="Embeds data protection and privacy-by-design into application architecture and coding patterns.",
            recommendation="Minimize data collection, apply defensive engineering patterns, and avoid vulnerable native functions.",
        ),
        Control(
            "Art.5(1)(f)",
            "Personal data is protected against unauthorised disclosure -- no credentials or personal data in source",
            "GDPR Art. 5(1)(f)",
            ControlSelector(kinds=frozenset({"secret"}), categories=frozenset({"sensitive-data"})),
            fail_severities=_ANY_SEVERITY,
            domain="Art. 5: Principles of Processing",
            description="Requires technical measures to prevent unauthorized disclosure, leakage, or accidental exposure of personal data and credentials in source code.",
            recommendation="Remove hardcoded credentials and sample personal data from repositories; implement automated secret detection pre-commit hooks.",
        ),
        Control(
            "Art.33-detect",
            "Breaches are detectable -- security-relevant events are logged",
            "GDPR Art. 33",
            _LOGGING,
            domain="Art. 33: Incident & Breach Detection",
            description="Maintains detailed logging of security events and unauthorized access attempts to enable timely breach detection and 72-hour reporting.",
            recommendation="Log failed authentication attempts, privilege changes, and administrative actions with correlation IDs.",
        ),
        _manual(
            "Art.6",
            "Processing has a valid lawful basis",
            "GDPR Art. 6",
            "Legal determination. Requires your record of processing activities and legal review -- no code scanner can establish a lawful basis.",
            domain="Governance & Legal",
        ),
        _manual(
            "Art.30",
            "Records of processing activities are maintained",
            "GDPR Art. 30",
            "Documentation obligation. Evidence it with your Article 30 record.",
            domain="Governance & Legal",
        ),
        _manual(
            "Art.33-notify",
            "Personal data breaches are notified to the supervisory authority within 72 hours",
            "GDPR Art. 33",
            "Process obligation. Evidence it with your breach notification procedure and register.",
            domain="Art. 33: Incident & Breach Detection",
        ),
        _manual(
            "Art.35",
            "A data protection impact assessment is carried out for high-risk processing",
            "GDPR Art. 35",
            "Assessment obligation. Evidence it with completed DPIAs.",
            domain="Governance & Legal",
        ),
        _manual(
            "Art.15-22",
            "Data subject rights can be exercised (access, erasure, portability, objection)",
            "GDPR Art. 15-22",
            "Process obligation. Evidence it with your data subject request workflow and SLA -- the presence of an endpoint is not evidence the right is honoured.",
            domain="Data Subject Rights",
        ),
        _manual(
            "Art.28",
            "Processors are engaged under a written data processing agreement",
            "GDPR Art. 28",
            "Contractual obligation. Evidence it with signed DPAs for every processor.",
            domain="Vendor & Third-Party Management",
        ),
    ],
)


HIPAA = Framework(
    key="hipaa",
    title="HIPAA Security Rule (Technical Safeguards)",
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
            domain="164.312: Technical Safeguards",
            description="Grants access to electronic protected health information (ePHI) strictly to persons or software programs that have been granted access rights.",
            recommendation="Implement strict role-based access control, session timeouts, and sanitize file path inputs against directory traversal.",
        ),
        Control(
            "164.312(a)(2)(iv)",
            "Encryption and decryption of ePHI at rest uses sound cryptography",
            "45 CFR 164.312(a)(2)(iv)",
            _CRYPTO,
            domain="164.312: Technical Safeguards",
            description="Implements a mechanism to encrypt and decrypt ePHI using verified cryptographic algorithms.",
            recommendation="Use AES-256 with authenticated encryption (e.g. GCM) for databases and blob storage containing healthcare records.",
        ),
        Control(
            "164.312(b)",
            "Audit controls record activity in systems containing ePHI",
            "45 CFR 164.312(b)",
            _LOGGING,
            domain="164.312: Technical Safeguards",
            description="Implements hardware, software, and procedural mechanisms that record and examine activity in systems containing or using ePHI.",
            recommendation="Maintain immutable audit logs recording read/write access to patient records with user IDs and timestamps.",
        ),
        Control(
            "164.312(c)(1)",
            "ePHI is protected from improper alteration or destruction",
            "45 CFR 164.312(c)(1)",
            _INJECTION,
            domain="164.312: Technical Safeguards",
            description="Protects ePHI from improper alteration or destruction through input validation and parameterized data interfaces.",
            recommendation="Use parameterized queries and strict schema validation on all healthcare record inputs.",
        ),
        Control(
            "164.312(d)",
            "Person or entity authentication is implemented securely",
            "45 CFR 164.312(d)",
            ControlSelector(
                categories=frozenset({"authentication"}), owasp=frozenset({"A07:2025"})
            ),
            domain="164.312: Technical Safeguards",
            description="Implements procedures to verify that a person or entity seeking access to ePHI is the one claimed.",
            recommendation="Enforce strong multi-factor authentication, secure password hashing, and short-lived session tokens.",
        ),
        Control(
            "164.312(e)(1)",
            "Transmission security guards ePHI against interception over networks",
            "45 CFR 164.312(e)(1)",
            ControlSelector(
                categories=frozenset({"insecure-transport", "ssrf"}),
                owasp=frozenset({"A02:2025", "A10:2025"}),
            ),
            domain="164.312: Technical Safeguards",
            description="Guards against unauthorized access to ePHI that is being transmitted over an electronic communications network.",
            recommendation="Enforce TLS 1.3 on all client and inter-service communications, with strict certificate validation.",
        ),
        Control(
            "164.308(a)(1)(ii)(B)-tech",
            "Identified technical vulnerabilities are reduced to a reasonable level",
            "45 CFR 164.308(a)(1)(ii)(B)",
            _DEPENDENCIES,
            domain="164.308: Administrative Safeguards",
            description="Applies security measures sufficient to reduce technical vulnerabilities in third-party packages to a reasonable and appropriate level.",
            recommendation="Perform automated vulnerability scanning and replace vulnerable third-party dependencies.",
        ),
        Control(
            "164.308(a)(5)(ii)(D)-tech",
            "Passwords and keys are managed -- not hardcoded into software",
            "45 CFR 164.308(a)(5)(ii)(D)",
            _SECRETS,
            fail_severities=_ANY_SEVERITY,
            domain="164.308: Administrative Safeguards",
            description="Guards against hardcoded credentials, master keys, or passwords stored in application source code.",
            recommendation="Move all database credentials and encryption keys into managed key vaults and rotate regularly.",
        ),
        Control(
            "164.312-config",
            "Systems handling ePHI are securely configured",
            "45 CFR 164.312",
            _MISCONFIG,
            domain="164.312: Technical Safeguards",
            description="Ensures systems and middleware handling ePHI are configured with secure default baselines.",
            recommendation="Disable debug modes, restrict CORS origins to trusted medical portal domains, and enable security headers.",
        ),
        _manual(
            "164.308(a)(1)(ii)(A)",
            "A risk analysis of ePHI confidentiality, integrity and availability is conducted",
            "45 CFR 164.308(a)(1)(ii)(A)",
            "Administrative safeguard. Evidence it with your documented security risk analysis.",
            domain="164.308: Administrative Safeguards",
        ),
        _manual(
            "164.308(a)(3)",
            "Workforce security: authorisation and supervision of workforce members",
            "45 CFR 164.308(a)(3)",
            "Administrative safeguard. Evidence it with role authorisation records and termination procedures.",
            domain="164.308: Administrative Safeguards",
        ),
        _manual(
            "164.308(a)(4)",
            "Information access management: policies for granting access to ePHI",
            "45 CFR 164.308(a)(4)",
            "Administrative safeguard. Evidence it with your access authorisation policy and periodic access reviews.",
            domain="164.308: Administrative Safeguards",
        ),
        _manual(
            "164.308(a)(6)",
            "Security incident procedures are documented and followed",
            "45 CFR 164.308(a)(6)",
            "Administrative safeguard. Evidence it with your incident response procedure and log.",
            domain="164.308: Administrative Safeguards",
        ),
        _manual(
            "164.308(a)(7)",
            "Contingency plan: data backup, disaster recovery and emergency mode operation",
            "45 CFR 164.308(a)(7)",
            "Administrative safeguard. Evidence it with tested backup and disaster recovery plans.",
            domain="164.308: Administrative Safeguards",
        ),
        _manual(
            "164.308(b)(1)",
            "Business associate contracts are in place before ePHI is disclosed",
            "45 CFR 164.308(b)(1)",
            "Contractual obligation. Evidence it with executed business associate agreements.",
            domain="164.308: Administrative Safeguards",
        ),
        _manual(
            "164.310",
            "Physical safeguards protect facilities and workstations holding ePHI",
            "45 CFR 164.310",
            "Physical safeguard. Evidence it with facility access controls and device inventory.",
            domain="164.310: Physical Safeguards",
        ),
    ],
)


PCIDSS = Framework(
    key="pcidss",
    title="PCI-DSS v4.0 (Payment Card Industry)",
    scope_note=(
        "Technical requirements of PCI-DSS v4.0 assessable from source code and application configuration "
        "(Requirements 3, 4, 6, 8, 10). Physical security, network segmentation, and operational policies "
        "require manual assessor evaluation."
    ),
    controls=[
        Control(
            "Req.3.4",
            "Primary account numbers (PAN) and cryptographic keys are protected against disclosure",
            "PCI-DSS v4.0 Req. 3.4",
            _SECRETS,
            fail_severities=_ANY_SEVERITY,
            domain="Requirement 3: Protect Account Data",
            description="Renders primary account numbers (PAN) unreadable anywhere it is stored and prevents hardcoding cryptographic keys in code.",
            recommendation="Never store plain PANs in code or config. Store API payment keys in hardware security modules or dedicated secrets managers.",
        ),
        Control(
            "Req.4.1",
            "Strong cryptography and secure transmission protocols protect cardholder data in transit",
            "PCI-DSS v4.0 Req. 4.1",
            _CRYPTO,
            domain="Requirement 4: Protect Data in Transit",
            description="Protects cardholder data with strong cryptography during transmission over open, public, or internal networks.",
            recommendation="Enforce TLS 1.2+ with forward secrecy ciphers on all payment processing endpoints.",
        ),
        Control(
            "Req.6.2.4",
            "Common software attacks (SQLi, XSS, Command Injection) are prevented",
            "PCI-DSS v4.0 Req. 6.2.4",
            _INJECTION,
            domain="Requirement 6: Secure Software",
            description="Defends custom software against common coding vulnerabilities including injection flaws, cross-site scripting, and unauthorized file access.",
            recommendation="Use parameterized queries, context-aware output encoding, and input validation schemas for all payment inputs.",
        ),
        Control(
            "Req.6.3.1",
            "Security vulnerabilities in custom software are identified and remediated",
            "PCI-DSS v4.0 Req. 6.3.1",
            _SECURE_DESIGN,
            domain="Requirement 6: Secure Software",
            description="Integrates security vulnerability reviews and defensive design into custom software development cycles.",
            recommendation="Run automated static application security testing (SAST) on every pull request and address design-level flaws.",
        ),
        Control(
            "Req.6.3.2",
            "Third-party software dependencies are inventoried and free of known vulnerabilities",
            "PCI-DSS v4.0 Req. 6.3.2",
            _DEPENDENCIES,
            domain="Requirement 6: Secure Software",
            description="Maintains an inventory of bespoke and custom software third-party libraries and actively manages known CVEs.",
            recommendation="Automate software composition analysis (SCA) and replace vulnerable packages prior to production release.",
        ),
        Control(
            "Req.6.4.1",
            "Applications protect against Server-Side Request Forgery (SSRF) and untrusted endpoints",
            "PCI-DSS v4.0 Req. 6.4.1",
            _SSRF,
            domain="Requirement 6: Secure Software",
            description="Guards payment applications against server-side request forgery (SSRF) and unauthorized internal resource requests.",
            recommendation="Validate all outbound HTTP request destinations against strict payment gateway allowlists.",
        ),
        Control(
            "Req.8.2.1",
            "Strong user identification and authentication controls are enforced",
            "PCI-DSS v4.0 Req. 8.2.1",
            _ACCESS_CONTROL,
            domain="Requirement 8: Identify Users & Access",
            description="Ensures multi-factor authentication, secure session handling, and robust access controls for all users accessing payment systems.",
            recommendation="Enforce MFA, secure cookie attributes, and validate permissions on all cardholder data access routes.",
        ),
        Control(
            "Req.10.2.1",
            "Audit logs capture all access to system components and cardholder data",
            "PCI-DSS v4.0 Req. 10.2.1",
            _LOGGING,
            domain="Requirement 10: Log & Monitor",
            description="Generates audit records for all user actions, privilege changes, and security events without recording sensitive authentication data.",
            recommendation="Log all payment API events and ensure CVV/PAN data is masked before logging.",
        ),
        Control(
            "Req.2.2.1",
            "System components are securely configured and unnecessary services disabled",
            "PCI-DSS v4.0 Req. 2.2.1",
            _MISCONFIG,
            domain="Requirement 2: Secure Configuration",
            description="Applies secure configuration standards to all application components and removes unnecessary functionality.",
            recommendation="Disable debug modes, remove unused modules, and enforce hardened HTTP security response headers.",
        ),
        Control(
            "Req.6.5.1",
            "Software build and deployment integrity protects against supply-chain tampering",
            "PCI-DSS v4.0 Req. 6.5.1",
            _INTEGRITY,
            domain="Requirement 6: Secure Software",
            description="Protects application builds and third-party software imports against supply chain tampering and unauthorized modification.",
            recommendation="Sign build artifacts and verify package checksums in the CI/CD pipeline.",
        ),
        _manual(
            "Req.1.1",
            "Network security controls (firewalls/NSGs) are installed and maintained",
            "PCI-DSS v4.0 Req. 1.1",
            "Network infrastructure control. Evidence it with firewall rule configurations and network segmentation diagrams.",
            domain="Requirement 1: Network Security",
        ),
        _manual(
            "Req.9.1",
            "Physical access to cardholder data and systems is restricted",
            "PCI-DSS v4.0 Req. 9.1",
            "Physical security control. Evidence it with facility access badges, visitor logs, and data center security reports.",
            domain="Requirement 9: Restrict Physical Access",
        ),
        _manual(
            "Req.11.3",
            "Periodic internal and external penetration testing is performed",
            "PCI-DSS v4.0 Req. 11.3",
            "Assessment control. Evidence it with annual penetration test reports and remediation verification.",
            domain="Requirement 11: Test Security Regularly",
        ),
        _manual(
            "Req.12.1",
            "An overall information security policy is established and maintained",
            "PCI-DSS v4.0 Req. 12.1",
            "Governance control. Evidence it with approved organizational security policies and executive sign-off.",
            domain="Requirement 12: Information Security Policy",
        ),
    ],
)


NIST80053 = Framework(
    key="nist80053",
    title="NIST SP 800-53 Rev. 5",
    scope_note=(
        "Technical control baselines across AC (Access Control), SC (System and Communications Protection), "
        "SI (System and Information Integrity), AU (Audit and Accountability), and SA (System and Services "
        "Acquisition) assessable from source code and dependency scans."
    ),
    controls=[
        Control(
            "AC-3",
            "Access enforcement prevents unauthorized information flows and operations",
            "NIST SP 800-53 r5 AC-3",
            _ACCESS_CONTROL,
            domain="Access Control (AC)",
            description="Enforces approved authorizations for logical access to information and system resources in accordance with applicable access control policies.",
            recommendation="Implement centralized RBAC/ABAC authorization middleware and validate permissions on every endpoint.",
        ),
        Control(
            "SC-8",
            "Transmission confidentiality and integrity is maintained using approved cryptography",
            "NIST SP 800-53 r5 SC-8",
            _CRYPTO,
            domain="System & Communications Protection (SC)",
            description="Protects the confidentiality and integrity of transmitted information using approved cryptographic mechanisms (FIPS-validated).",
            recommendation="Use TLS 1.3/1.2 with strong cipher suites across all communication channels.",
        ),
        Control(
            "SC-28",
            "Protection of information at rest and prevention of credential leakage in source",
            "NIST SP 800-53 r5 SC-28",
            _SECRETS,
            fail_severities=_ANY_SEVERITY,
            domain="System & Communications Protection (SC)",
            description="Protects the confidentiality and integrity of information at rest and prevents committing keys or sensitive data to code repositories.",
            recommendation="Enforce secrets vault integration and scan code repositories for hardcoded credentials.",
        ),
        Control(
            "SI-10",
            "Information input validation defends against code injection and memory corruption",
            "NIST SP 800-53 r5 SI-10",
            _INJECTION,
            domain="System & Information Integrity (SI)",
            description="Validates data inputs to applications against syntax and semantics rules to prevent injection, buffer overflows, and script execution.",
            recommendation="Implement strict input validation schemas and use parameterized interfaces for all system operations.",
        ),
        Control(
            "SI-2",
            "Flaw remediation: Identify, report, and remediate software vulnerabilities promptly",
            "NIST SP 800-53 r5 SI-2",
            _DEPENDENCIES,
            domain="System & Information Integrity (SI)",
            description="Identifies, reports, and corrects system flaws and third-party software package vulnerabilities within defined timeframes.",
            recommendation="Establish automated SCA dependency scanning and patch high/critical vulnerabilities promptly.",
        ),
        Control(
            "SI-4",
            "System monitoring identifies unauthorized connections and atypical communications",
            "NIST SP 800-53 r5 SI-4",
            _SSRF,
            domain="System & Information Integrity (SI)",
            description="Monitors the system to detect attacks and indicators of potential compromise, including unauthorized outbound connections (SSRF).",
            recommendation="Enforce outbound proxy filtering and validate all destination endpoints against allowlists.",
        ),
        Control(
            "AU-2",
            "Audit events: Generate audit records for security-relevant system operations",
            "NIST SP 800-53 r5 AU-2",
            _LOGGING,
            domain="Audit & Accountability (AU)",
            description="Identifies that the system is capable of generating audit records for defined security-relevant events.",
            recommendation="Implement structured application audit logging for authentication, access changes, and system faults.",
        ),
        Control(
            "CM-6",
            "Configuration settings adhere to hardened, secure application baselines",
            "NIST SP 800-53 r5 CM-6",
            _MISCONFIG,
            domain="Configuration Management (CM)",
            description="Establishes and documents mandatory configuration settings for information technology products employed within the system.",
            recommendation="Harden framework and container configurations, disable unnecessary services, and apply secure header policies.",
        ),
        Control(
            "SA-11",
            "Developer testing and evaluation includes static code security analysis",
            "NIST SP 800-53 r5 SA-11",
            _SECURE_DESIGN,
            domain="System & Services Acquisition (SA)",
            description="Requires developer testing and evaluation, including static code analysis and threat model risk validation.",
            recommendation="Integrate SAST into CI pipelines to catch race conditions and dangerous function invocations before merge.",
        ),
        Control(
            "SR-3",
            "Supply chain controls protect against compromised dependencies and tampering",
            "NIST SP 800-53 r5 SR-3",
            _INTEGRITY,
            domain="Supply Chain Risk Management (SR)",
            description="Establishes and maintains controls to mitigate risks of compromised software packages and supply chain tampering.",
            recommendation="Pin dependency hashes, verify package signatures, and review third-party components before inclusion.",
        ),
        _manual(
            "AT-2",
            "Personnel receive basic role-based security training",
            "NIST SP 800-53 r5 AT-2",
            "People control. Evidence it with annual security awareness training logs and role-specific curriculum records.",
            domain="Awareness & Training (AT)",
        ),
        _manual(
            "IR-4",
            "Incident handling capabilities are established and tested",
            "NIST SP 800-53 r5 IR-4",
            "Process control. Evidence it with incident handling playbooks, tabletop exercises, and response metrics.",
            domain="Incident Response (IR)",
        ),
        _manual(
            "PL-2",
            "System security and privacy plans are documented and approved",
            "NIST SP 800-53 r5 PL-2",
            "Documentation control. Evidence it with the approved System Security Plan (SSP).",
            domain="Planning (PL)",
        ),
        _manual(
            "RA-3",
            "Periodic risk assessments evaluate threat environment and control effectiveness",
            "NIST SP 800-53 r5 RA-3",
            "Governance control. Evidence it with formal risk assessment reports and risk register updates.",
            domain="Risk Assessment (RA)",
        ),
    ],
)


FRAMEWORKS: dict[str, Framework] = {
    f.key: f for f in (SOC2, ISO27001, GDPR, HIPAA, PCIDSS, NIST80053)
}

# Stable order for the wizard and the results view.
FRAMEWORK_KEYS_ORDERED: list[str] = list(FRAMEWORKS)


def get_framework(key: str) -> Framework | None:
    return FRAMEWORKS.get(key)
