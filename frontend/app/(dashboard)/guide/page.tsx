import {
  BookOpen,
  Cloud,
  FolderPlus,
  GitBranch,
  Key,
  ListChecks,
  ShieldCheck,
  Sparkles,
  Terminal,
  TriangleAlert,
  Wand2,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * The developer guide. Static, hand-written prose — deliberately not generated from
 * the API, because the thing a newcomer needs is the *order of operations*, which no
 * schema encodes.
 *
 * The "screens" on this page are schematic mocks built from the real design tokens,
 * not screenshots. Screenshots would rot on every UI change and would either leak a
 * real workspace's security posture or invent a fake one; a sketch that names the
 * real buttons ages far better and stays honest about being an illustration.
 */

/**
 * Server-rendered, so there is no `window.location.origin` to fall back on the way the
 * scan wizard does. When the env var is unset the commands below carry an obvious
 * placeholder rather than a plausible-looking wrong host — and every section that shows a
 * command also says the wizard emits the same command with the real URL and token filled in.
 */
const PORTAL = process.env.NEXT_PUBLIC_SCANNER_SERVER_ORIGIN ?? "<PORTAL_URL>";

const TOC: { id: string; label: string }[] = [
  { id: "orientation", label: "How it fits together" },
  { id: "onboard", label: "1. Onboard a project" },
  { id: "scan", label: "2. Run a scan" },
  { id: "results", label: "3. Read the results" },
  { id: "ai", label: "4. Turn on AI analysis" },
  { id: "autofix", label: "5. Auto-Fix a scan" },
  { id: "compliance", label: "6. Compliance audits" },
  { id: "admin", label: "Admin-only controls" },
  { id: "gotchas", label: "Gotchas" },
];

function Section({
  id,
  title,
  icon: Icon,
  lede,
  children,
}: {
  id: string;
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  lede: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-6 space-y-4 border-t border-border pt-8 first:border-0 first:pt-0">
      <div className="space-y-1.5">
        <h2 className="flex items-center gap-2.5 font-mono text-lg font-bold tracking-[-0.03em] text-foreground">
          <Icon className="size-4 text-signal" />
          {title}
        </h2>
        <p className="max-w-[80ch] text-sm leading-relaxed text-muted-foreground">{lede}</p>
      </div>
      {children}
    </section>
  );
}

/** Numbered step. The number is the lime marker used everywhere else in the app. */
function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3.5">
      <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-sm bg-signal font-mono text-[12px] font-bold text-signal-foreground">
        {n}
      </span>
      <div className="min-w-0 space-y-1.5 pb-1">
        <p className="font-mono text-[13px] font-semibold tracking-[-0.01em] text-foreground">{title}</p>
        <div className="max-w-[80ch] space-y-2 text-sm leading-relaxed text-muted-foreground">{children}</div>
      </div>
    </li>
  );
}

function Steps({ children }: { children: ReactNode }) {
  return <ol className="space-y-4">{children}</ol>;
}

/**
 * A framed sketch of a screen. The chrome bar makes it read as "here is what you
 * will see", so the sketch is never mistaken for live data on this page.
 */
function Screen({ label, children }: { label: string; children: ReactNode }) {
  return (
    <figure className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border bg-muted/50 px-3 py-2">
        <span className="size-2 rounded-full bg-severity-critical/60" />
        <span className="size-2 rounded-full bg-severity-medium/60" />
        <span className="size-2 rounded-full bg-severity-low/60" />
        <figcaption className="legend ml-1.5 truncate text-muted-foreground">{label}</figcaption>
      </div>
      <div className="p-3.5">{children}</div>
    </figure>
  );
}

/** Fake button — looks like the real one, does nothing. Keeps this page server-rendered. */
function FauxButton({ children, tone = "outline" }: { children: ReactNode; tone?: "solid" | "outline" }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center rounded-sm px-2.5 font-mono text-[11px] font-semibold tracking-[-0.01em]",
        tone === "solid"
          ? "bg-signal text-signal-foreground"
          : "border border-border bg-background text-muted-foreground"
      )}
    >
      {children}
    </span>
  );
}

function SevChip({ level }: { level: "critical" | "high" | "medium" | "low" | "info" }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-sm px-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.06em]",
        level === "critical" && "bg-severity-critical-tint text-severity-critical",
        level === "high" && "bg-severity-high-tint text-severity-high",
        level === "medium" && "bg-severity-medium-tint text-severity-medium",
        level === "low" && "bg-severity-low-tint text-severity-low",
        level === "info" && "bg-severity-info-tint text-severity-info"
      )}
    >
      {level}
    </span>
  );
}

function Cmd({ children }: { children: ReactNode }) {
  return (
    <pre className="overflow-x-auto rounded-sm border border-border bg-muted px-3 py-2 font-mono text-[12px] leading-relaxed text-foreground">
      {children}
    </pre>
  );
}

function Note({ children }: { children: ReactNode }) {
  return (
    <p className="max-w-[80ch] border-l-2 border-signal bg-signal/5 px-3 py-2 text-[13px] leading-relaxed text-muted-foreground">
      {children}
    </p>
  );
}

function Jump({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="font-medium text-foreground underline decoration-signal decoration-2 underline-offset-2">
      {children}
    </Link>
  );
}

export default function GuidePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="DOCS / DEVELOPER GUIDE"
        title="Developer Guide"
        description="Everything a developer does in ZeroStrike, in the order you actually do it: onboard a project, get a scan running, read findings, switch on AI analysis, ship an Auto-Fix PR, run a compliance audit."
      />

      <div className="grid gap-8 lg:grid-cols-[210px_minmax(0,1fr)]">
        {/* In-page nav. Plain anchors — no scroll-spy, the browser already does the work. */}
        <nav className="hidden lg:block">
          <div className="sticky top-6 space-y-0.5">
            <p className="legend mb-2 px-2.5 text-muted-foreground">On this page</p>
            {TOC.map((t) => (
              <a
                key={t.id}
                href={`#${t.id}`}
                className="block rounded-sm px-2.5 py-1.5 font-mono text-[12px] tracking-[-0.01em] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                {t.label}
              </a>
            ))}
          </div>
        </nav>

        <div className="min-w-0 space-y-8">
          {/* ─────────────────────────── Orientation ─────────────────────────── */}
          <Section
            id="orientation"
            title="How it fits together"
            icon={Workflow}
            lede="ZeroStrike is a SAST scanner plus a portal that stores and acts on what it finds. The scanner is a single Go binary; the portal is where scans, findings, fixes and audits live. Everything below hangs off one pipeline."
          >
            <Screen label="the pipeline">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-2 font-mono text-[12px] text-muted-foreground">
                {["project", "repository", "scan", "findings", "AI analysis", "Auto-Fix PR", "compliance audit"].map(
                  (stage, i) => (
                    <span key={stage} className="flex items-center gap-2">
                      {i > 0 && <span className="text-signal">→</span>}
                      <span className="rounded-sm border border-border bg-background px-2 py-1 text-foreground">
                        {stage}
                      </span>
                    </span>
                  )
                )}
              </div>
            </Screen>

            <div className="grid gap-3 sm:grid-cols-3">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">A project</CardTitle>
                </CardHeader>
                <CardContent className="text-sm leading-relaxed text-muted-foreground">
                  The unit of access and configuration. Members, repositories, tokens, policy and audits all
                  belong to a project. Nothing scans until one exists.
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">A scan</CardTitle>
                </CardHeader>
                <CardContent className="text-sm leading-relaxed text-muted-foreground">
                  One run of the scanner over one repository at one commit. It produces findings and a report,
                  and it is the scope for AI analysis, Auto-Fix and audit evidence.
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Everything else</CardTitle>
                </CardHeader>
                <CardContent className="text-sm leading-relaxed text-muted-foreground">
                  AI analysis, Auto-Fix and compliance audits are all read-side consumers of scans. If a
                  surface looks empty, the answer is almost always &ldquo;no scan in scope yet&rdquo;.
                </CardContent>
              </Card>
            </div>

            <Note>
              Order of operations, memorised once:{" "}
              <span className="font-mono text-foreground">project → repo → scan → everything else</span>. The
              product deliberately refuses to fake the later steps without the earlier ones — an audit with no
              scans in scope is rejected rather than rendered as all-pass.
            </Note>
          </Section>

          {/* ─────────────────────────── Onboard ─────────────────────────── */}
          <Section
            id="onboard"
            title="1. Onboard a project"
            icon={FolderPlus}
            lede="Two things to create: the project, and a connection to the code. Repository credentials live on your user account and get copied into a project connection, so you enter a PAT once and reuse it across projects."
          >
            <Steps>
              <Step n={1} title="Create the project">
                <p>
                  <Jump href="/projects/new">Projects → New project</Jump>. Name it after the thing being
                  scanned, not the team — findings, audits and PRs all get labelled with it.
                </p>
              </Step>
              <Step n={2} title="Store a repository credential (once per provider)">
                <p>
                  <Jump href="/settings/integrations">Settings → Integrations</Jump>. Add a personal access
                  token for GitHub / GitLab / Azure DevOps / Bitbucket. It is stored against your user, not the
                  project, and is never echoed back after saving.
                </p>
              </Step>
              <Step n={3} title="Connect a repository to the project">
                <p>
                  Open the project → <span className="font-mono text-foreground">Repositories</span> → connect.
                  The wizard lists repos the credential can see, so you pick rather than paste a URL. A project
                  can hold several repositories; each scan targets one.
                </p>
              </Step>
              <Step n={4} title="Know your way around the project workspace">
                <p>
                  Every project has the same left rail. Deep-linkable — the tab is in the URL as{" "}
                  <span className="font-mono text-foreground">?tab=…</span>, so you can bookmark or share any
                  view.
                </p>
              </Step>
            </Steps>

            <Screen label="project workspace — left rail">
              <div className="flex w-full max-w-[260px] flex-col gap-0.5 font-mono text-[12px]">
                {[
                  { label: "Project Overview", active: true },
                  { label: "SAST Code Scanner" },
                  { label: "Scan History" },
                  { label: "AI Auto-Fix" },
                  { label: "AI Auditor & Tokens" },
                  { label: "Compliance Audits" },
                  { label: "OWASP Top 10" },
                  { label: "Compliance Config" },
                  { label: "Repositories" },
                  { label: "Members & Access" },
                  { label: "Project Tokens" },
                  { label: "Project Settings" },
                ].map((item) => (
                  <span
                    key={item.label}
                    className={cn(
                      "relative px-3 py-1.5",
                      item.active
                        ? "bg-accent font-semibold text-foreground"
                        : "text-muted-foreground"
                    )}
                  >
                    {item.active && <span className="absolute inset-y-0 left-0 w-[3px] bg-signal" />}
                    {item.label}
                  </span>
                ))}
              </div>
            </Screen>
          </Section>

          {/* ─────────────────────────── Scan ─────────────────────────── */}
          <Section
            id="scan"
            title="2. Run a scan"
            icon={ListChecks}
            lede="Three ways in, same scanner and same findings at the end. Pick by where the code is when you want it scanned. Start from the project → SAST Code Scanner → New scan."
          >
            <Screen label="New scan — pick a type">
              <div className="grid gap-2.5 sm:grid-cols-3">
                {[
                  {
                    icon: Terminal,
                    label: "Local",
                    body: "Run the ZeroStrike CLI on your machine and upload results with a project token.",
                  },
                  {
                    icon: Cloud,
                    label: "Cloud",
                    body: "Give ZeroStrike a repo URL and it clones + scans it server-side.",
                  },
                  {
                    icon: GitBranch,
                    label: "CI/CD",
                    body: "Add ZeroStrike to your pipeline (GitHub Actions, GitLab CI, Azure Pipelines).",
                  },
                ].map((t) => (
                  <div key={t.label} className="space-y-2 rounded-sm border border-border p-3">
                    <t.icon className="size-4 text-signal" />
                    <p className="font-mono text-[13px] font-semibold text-foreground">{t.label}</p>
                    <p className="text-[12px] leading-relaxed text-muted-foreground">{t.body}</p>
                  </div>
                ))}
              </div>
            </Screen>

            <div className="space-y-5">
              <div className="space-y-2">
                <h3 className="flex items-center gap-2 font-mono text-[13px] font-bold tracking-[-0.01em] text-foreground">
                  <Terminal className="size-3.5 text-signal" /> Local — fastest feedback, code never leaves your
                  machine
                </h3>
                <p className="max-w-[80ch] text-sm leading-relaxed text-muted-foreground">
                  The wizard generates a project token for you (shown once) and hands you a two-line command.
                  Download the binary from this portal — no registry, no credentials needed to fetch it:
                </p>
                <Cmd>
                  {`curl -fsSL ${PORTAL}/api/v1/downloads/zerostrike/latest/linux-amd64 -o zerostrike && chmod +x zerostrike
./zerostrike scan . --server ${PORTAL} --token <PROJECT_TOKEN>`}
                </Cmd>
                <p className="max-w-[80ch] text-sm leading-relaxed text-muted-foreground">
                  The CLI scans locally and uploads only the report. The scan then appears in the project like
                  any other. Copy the command from the wizard rather than from here — it comes out with this
                  portal&apos;s real URL, your OS&apos;s install line and a freshly generated token already
                  filled in.
                </p>
              </div>

              <div className="space-y-2">
                <h3 className="flex items-center gap-2 font-mono text-[13px] font-bold tracking-[-0.01em] text-foreground">
                  <Cloud className="size-3.5 text-signal" /> Cloud — one click, nothing installed
                </h3>
                <p className="max-w-[80ch] text-sm leading-relaxed text-muted-foreground">
                  Pick a connected repository and a branch; the portal clones it shallow, runs the scanner
                  server-side and ingests the report. Queued scans run up to a workspace concurrency limit and
                  are picked up by a poll loop, so a queued scan is normal — not stuck.
                </p>
                <p className="max-w-[80ch] text-sm leading-relaxed text-muted-foreground">
                  This is the only path that needs the repository credential at scan time, and the only one
                  that can feed Auto-Fix pull requests without you running anything.
                </p>
              </div>

              <div className="space-y-2">
                <h3 className="flex items-center gap-2 font-mono text-[13px] font-bold tracking-[-0.01em] text-foreground">
                  <GitBranch className="size-3.5 text-signal" /> CI/CD — the gate
                </h3>
                <p className="max-w-[80ch] text-sm leading-relaxed text-muted-foreground">
                  The wizard emits a ready pipeline snippet for GitHub Actions, GitLab CI or Azure Pipelines,
                  plus the project token to store as a CI secret. It downloads the binary from this portal at
                  job time, scans the checkout and uploads. Blocking severities are workspace policy, so the
                  pipeline fails on what the workspace decided is unacceptable — not on a per-repo guess.
                </p>
                <Cmd>{`- run: ./zerostrike scan . --server ${PORTAL} --token $ZEROSTRIKE_TOKEN`}</Cmd>
                <p className="max-w-[80ch] text-sm leading-relaxed text-muted-foreground">
                  Take the full snippet from the wizard — it is generated with this portal&apos;s real URL and
                  the download step for the runner&apos;s platform.
                </p>
              </div>
            </div>

            <Note>
              <span className="font-mono text-foreground">Project tokens</span>{" "}
              are the CLI/CI credential and
              are project-scoped — they can create and upload scans for one project and nothing else. Manage
              them under the project&apos;s <span className="font-mono text-foreground">Project Tokens</span>{" "}
              tab. The raw token is shown exactly once; regenerate if it is lost.
            </Note>
          </Section>

          {/* ─────────────────────────── Results ─────────────────────────── */}
          <Section
            id="results"
            title="3. Read the results"
            icon={Key}
            lede="A completed scan gives you a findings list and a report. The findings list is the working surface: filter it, expand a finding for the offending code, and act from there."
          >
            <Screen label="scan detail — a finding row expanded">
              <div className="space-y-2.5">
                <div className="flex flex-wrap items-center gap-2 border-b border-border pb-2.5">
                  <SevChip level="critical" />
                  <span className="font-mono text-[12px] font-semibold text-foreground">
                    SQL injection via string concatenation
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    src/handlers/report.py:142
                  </span>
                </div>
                <div className="space-y-2 rounded-sm border border-border bg-muted/40 p-2.5">
                  <p className="legend text-muted-foreground">Evidence</p>
                  <pre className="overflow-x-auto font-mono text-[11px] leading-relaxed text-muted-foreground">
                    {`142 |  cursor.execute("SELECT * FROM r WHERE id = " + rid)`}
                  </pre>
                  <div className="flex flex-wrap gap-2 pt-1">
                    <FauxButton>Analyze with AI</FauxButton>
                    <FauxButton tone="solid">Generate Fix</FauxButton>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  <SevChip level="high" />
                  <SevChip level="medium" />
                  <SevChip level="low" />
                  <SevChip level="info" />
                  <span className="font-mono text-[11px] text-muted-foreground">
                    every severity is listed — the list is never truncated to criticals
                  </span>
                </div>
              </div>
            </Screen>

            <Steps>
              <Step n={1} title="Triage from the list">
                <p>
                  Filter by severity, category or file. Expand a finding to see the offending lines, the rule
                  that fired and its OWASP category. Two actions live on every expanded finding:{" "}
                  <span className="font-mono text-foreground">Analyze with AI</span> and{" "}
                  <span className="font-mono text-foreground">Generate Fix</span> — both greyed out until an AI
                  provider is active.
                </p>
              </Step>
              <Step n={2} title="Check the OWASP view for shape, not detail">
                <p>
                  The project&apos;s <span className="font-mono text-foreground">OWASP Top 10</span>{" "}
                  tab
                  answers &ldquo;what kind of problem do we keep having&rdquo;, which a flat list buries.
                </p>
              </Step>
              <Step n={3} title="Export a report when someone outside needs it">
                <p>
                  Each scan carries its raw report; report templates are configured under{" "}
                  <Jump href="/settings/report-templates">Settings → Report Templates</Jump> and a project can
                  override the default.
                </p>
              </Step>
            </Steps>
          </Section>

          {/* ─────────────────────────── AI ─────────────────────────── */}
          <Section
            id="ai"
            title="4. Turn on AI analysis"
            icon={Sparkles}
            lede="Nothing AI-shaped works until a provider is configured — that is the single most common reason a button on this page looks broken. Configure it once, at whichever scope you want to pay from."
          >
            <Steps>
              <Step n={1} title="Configure a provider">
                <p>
                  <Jump href="/settings/ai-provider">Settings → AI Provider</Jump>. An admin sets the
                  portal-wide provider that every project uses by default. Failover providers can be ordered
                  there too.
                </p>
              </Step>
              <Step n={2} title="Or give one project its own key (BYOK)">
                <p>
                  With project BYOK enabled workspace-wide, a project can hold its own provider config. A
                  project on BYOK runs <em>only</em>{" "}
                  on its own key — it never silently falls back to the
                  portal&apos;s. That is deliberate: cost attribution you can trust is worth more than a
                  request that quietly succeeds on someone else&apos;s budget.
                </p>
              </Step>
              <Step n={3} title="Analyse a finding">
                <p>
                  Expand a finding →{" "}
                  <span className="font-mono text-foreground">Analyze with AI</span>. You get an explanation of
                  why it is exploitable, in the context of the surrounding code. The result is cached against
                  the finding&apos;s fingerprint, so re-opening it does not re-spend.
                </p>
              </Step>
              <Step n={4} title="Watch what it costs">
                <p>
                  Per project: the <span className="font-mono text-foreground">AI Auditor &amp; Tokens</span>{" "}
                  tab. Portal-wide: <Jump href="/admin/ai-analytics">Admin → AI Analytics</Jump>. Every call,
                  success or failure, is logged with latency, tokens and cost — and never with the prompt or
                  response content.
                </p>
              </Step>
            </Steps>
            <Note>
              If <span className="font-mono text-foreground">Analyze with AI</span> is disabled, check in this
              order: is a provider configured at all, is the project on BYOK without its own key, and does the
              finding have a fingerprint (very old scans may not).
            </Note>
          </Section>

          {/* ─────────────────────────── Auto-Fix ─────────────────────────── */}
          <Section
            id="autofix"
            title="5. Auto-Fix a scan"
            icon={Wand2}
            lede="Auto-Fix proposes patches, you review them, and approving a batch produces one branch and one pull request. Three separate limits govern it, and confusing any two of them is the classic mistake."
          >
            <Steps>
              <Step n={1} title="Check policy first">
                <p>
                  <Jump href="/settings/auto-fix">Settings → Auto-fix</Jump> holds the workspace switch, the
                  confidence threshold, per-run and per-scan allowances, and blocking severities. A project may{" "}
                  <em>tighten</em> these — disable auto-fix, raise the threshold — but never loosen them.
                </p>
              </Step>
              <Step n={2} title="Trigger a run on a scan">
                <p>
                  From the scan, or from the project&apos;s{" "}
                  <span className="font-mono text-foreground">AI Auto-Fix</span>{" "}
                  tab. One run only picks
                  findings that have no proposal yet, so clicking again advances through a large scan instead of
                  regenerating the same top slice. No button promises &ldquo;all&rdquo; — no single run can
                  deliver it, and the workspace names what is still uncovered.
                </p>
              </Step>
              <Step n={3} title="Review each proposal">
                <p>
                  Patch, evidence, the checks that ran, discussion and activity — all on the proposal. Approve
                  or reject per proposal, or select several and approve as a batch.
                </p>
              </Step>
              <Step n={4} title="Approve → one PR">
                <p>
                  An approve job writes one branch and one PR for the whole batch, scoped to a single scan (so
                  the repo and base branch are unambiguous by construction). The apply step re-scans the
                  combined diff, drops anything that drifted or introduced a new blocking finding, retries the
                  survivors once, and lists every drop in the PR body. A new blocking finding in a file no patch
                  touched aborts the batch rather than guessing which patch to blame.
                </p>
              </Step>
            </Steps>

            <Screen label="Auto-Fix workspace — a proposal">
              <div className="space-y-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <SevChip level="high" />
                  <span className="font-mono text-[12px] font-semibold text-foreground">
                    Parameterise the query
                  </span>
                  <span className="rounded-sm border border-border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
                    confidence 0.91
                  </span>
                </div>
                <div className="flex flex-wrap gap-1 border-b border-border pb-2 font-mono text-[11px]">
                  {["Patch", "Evidence", "Checks", "Discussion", "Activity"].map((t, i) => (
                    <span
                      key={t}
                      className={cn(
                        "rounded-sm px-2 py-1",
                        i === 0 ? "bg-accent font-semibold text-foreground" : "text-muted-foreground"
                      )}
                    >
                      {t}
                    </span>
                  ))}
                </div>
                <pre className="overflow-x-auto font-mono text-[11px] leading-relaxed">
                  <span className="text-severity-critical">
                    {`- cursor.execute("SELECT * FROM r WHERE id = " + rid)`}
                  </span>
                  {"\n"}
                  <span className="text-signal">
                    {`+ cursor.execute("SELECT * FROM r WHERE id = %s", (rid,))`}
                  </span>
                </pre>
                <div className="flex flex-wrap gap-2 pt-1">
                  <FauxButton tone="solid">Approve</FauxButton>
                  <FauxButton>Reject</FauxButton>
                  <FauxButton>Ask a question</FauxButton>
                </div>
              </div>
            </Screen>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th className="py-2 pr-4 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                      Limit
                    </th>
                    <th className="py-2 pr-4 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                      What it bounds
                    </th>
                    <th className="py-2 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                      Who sets it
                    </th>
                  </tr>
                </thead>
                <tbody className="text-muted-foreground">
                  <tr className="border-b border-border/60">
                    <td className="py-2 pr-4 font-mono text-[12px] text-foreground">max findings per job</td>
                    <td className="py-2 pr-4">One run. Click again to advance.</td>
                    <td className="py-2">Admin</td>
                  </tr>
                  <tr className="border-b border-border/60">
                    <td className="py-2 pr-4 font-mono text-[12px] text-foreground">findings per scan</td>
                    <td className="py-2 pr-4">The scan&apos;s total spend, plus any granted quota.</td>
                    <td className="py-2">Admin</td>
                  </tr>
                  <tr>
                    <td className="py-2 pr-4 font-mono text-[12px] text-foreground">— nothing —</td>
                    <td className="py-2 pr-4">
                      What the workspace <em>lists</em>. Every finding is always shown.
                    </td>
                    <td className="py-2">By design</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Section>

          {/* ─────────────────────────── Compliance ─────────────────────────── */}
          <Section
            id="compliance"
            title="6. Compliance audits"
            icon={ShieldCheck}
            lede="An audit maps scanner findings onto framework controls, deterministically. Its shape is configuration, not a per-run questionnaire — so running one is a single click once the project is configured."
          >
            <Steps>
              <Step n={1} title="Configure once">
                <p>
                  Project → <span className="font-mono text-foreground">Compliance Config</span> sets
                  frameworks, evidence scope (latest scan vs all history), whether an audit runs automatically
                  after every scan, and evidence retention. Defaults come from{" "}
                  <Jump href="/settings/general">Settings → General</Jump>; a project may override them.
                </p>
              </Step>
              <Step n={2} title="Run it">
                <p>
                  Project → <span className="font-mono text-foreground">Compliance Audits</span> →{" "}
                  <span className="font-mono text-foreground">Run Audit</span>. No wizard, no options — it uses
                  the configured policy. <span className="font-mono text-foreground">SOC 2</span> and{" "}
                  <span className="font-mono text-foreground">ISO 27001</span> are the runnable frameworks;
                  others exist in the catalogue only so historical audits still render.
                </p>
              </Step>
              <Step n={3} title="Read the verdicts correctly">
                <p>
                  Only the deterministic evaluator sets a control&apos;s status. The optional AI narrative
                  writes advisory prose for controls that already failed and can never move a verdict. A control
                  with no code-assessable signal is{" "}
                  <span className="font-mono text-foreground">needs manual review</span> — never a pass.
                </p>
              </Step>
            </Steps>

            <Screen label="audit detail — control rows">
              <div className="space-y-1.5 font-mono text-[12px]">
                {[
                  { id: "CC6.1", label: "Logical access — injection defences", state: "pass" },
                  { id: "CC7.1", label: "Vulnerability identification", state: "fail" },
                  { id: "CC1.4", label: "Personnel competence", state: "manual" },
                ].map((c) => (
                  <div
                    key={c.id}
                    className="flex flex-wrap items-center gap-2 rounded-sm border border-border px-2.5 py-2"
                  >
                    <span className="text-muted-foreground">{c.id}</span>
                    <span className="min-w-0 flex-1 truncate text-foreground">{c.label}</span>
                    <span
                      className={cn(
                        "rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.06em]",
                        c.state === "pass" && "bg-severity-low-tint text-severity-low",
                        c.state === "fail" && "bg-severity-critical-tint text-severity-critical",
                        c.state === "manual" && "bg-severity-info-tint text-severity-info"
                      )}
                    >
                      {c.state === "manual" ? "needs manual review" : c.state}
                    </span>
                  </div>
                ))}
              </div>
            </Screen>

            <Note>
              The <span className="font-mono text-foreground">compliance score</span> is scored over
              code-assessable controls only. It is <em>not</em> a compliance percentage, and the audit shows its
              coverage next to it so the difference stays visible. Do not quote it as one.
            </Note>
          </Section>

          {/* ─────────────────────────── Admin ─────────────────────────── */}
          <Section
            id="admin"
            title="Admin-only controls"
            icon={BookOpen}
            lede="Anything that authorises spend or grants access is portal-admin only and has no project override. If a page below refuses to load its data or hides its controls for you, you are not an admin — that is the intended behaviour, not a bug."
          >
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                {
                  href: "/admin/users",
                  label: "Users",
                  body: "Invite, promote, deactivate. Role changes are recorded in the audit log as privilege events.",
                },
                {
                  href: "/admin/auto-fix-requests",
                  label: "Project Requests",
                  body: "Projects asking for extra Auto-Fix allowance. Granting quota is a spend decision.",
                },
                {
                  href: "/admin/audit-log",
                  label: "Audit Log",
                  body: "Immutable. Bucketed into privilege / project / admin, with counts over the whole window.",
                },
                {
                  href: "/admin/scanner-status",
                  label: "Scanner Status",
                  body: "Which scanner build the running image actually ships, and whether scans are draining.",
                },
                {
                  href: "/admin/ai-analytics",
                  label: "AI Analytics",
                  body: "Portal-wide AI spend, latency and error rates across every project.",
                },
                {
                  href: "/settings/general",
                  label: "Workspace defaults",
                  body: "Analysers, frameworks, retention — plus a scope map of every setting and who owns it.",
                },
              ].map((a) => (
                <Link
                  key={a.href}
                  href={a.href}
                  className="group block rounded-lg border border-border bg-card p-3.5 transition-colors hover:border-signal/50 hover:bg-accent/40"
                >
                  <p className="font-mono text-[13px] font-semibold tracking-[-0.01em] text-foreground">
                    {a.label}
                  </p>
                  <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{a.body}</p>
                </Link>
              ))}
            </div>
          </Section>

          {/* ─────────────────────────── Gotchas ─────────────────────────── */}
          <Section
            id="gotchas"
            title="Gotchas"
            icon={TriangleAlert}
            lede="The failures that look like bugs and are not. Each of these has cost somebody an afternoon."
          >
            <div className="space-y-3">
              {[
                {
                  q: "A cloud scan fails with “executable not found”.",
                  a: "The deployment has no scanner binary configured. That is an operator fix, not a project one — ask an admin to check Scanner Status.",
                },
                {
                  q: "A cloud scan is refused for a repository that clearly exists.",
                  a: "Repo URLs are validated against loopback, private, link-local and cloud-metadata addresses before cloning. An internal host will be rejected on purpose.",
                },
                {
                  q: "A scan sits at “queued”.",
                  a: "Concurrency is capped workspace-wide and a poll loop claims the oldest queued scan. Queued is normal. A scan stuck in “running” far past the timeout is reaped automatically.",
                },
                {
                  q: "Every AI button is greyed out.",
                  a: "No active provider for this project. If the project is on BYOK, it needs its own key — it will never borrow the portal's.",
                },
                {
                  q: "Auto-Fix keeps showing the same ten proposals.",
                  a: "It doesn't. Each run picks findings with no proposal yet; the count grows as you re-run. The workspace lists what is still uncovered.",
                },
                {
                  q: "The audit refused to run.",
                  a: "No scans in scope, or an unsupported framework was requested. An empty audit is refused rather than shown as all-pass.",
                },
                {
                  q: "Nobody got the notification email.",
                  a: "Email is a no-op until SMTP is configured on the deployment; in-app notifications still fire. The notifications page says so plainly.",
                },
                {
                  q: "A project token stopped working.",
                  a: "Tokens expire (90 days by default when generated from the scan wizard) and the raw value is only ever shown once. Generate a new one under Project Tokens.",
                },
              ].map((g) => (
                <div key={g.q} className="rounded-lg border border-border bg-card p-3.5">
                  <p className="font-mono text-[13px] font-semibold tracking-[-0.01em] text-foreground">{g.q}</p>
                  <p className="mt-1.5 max-w-[80ch] text-[13px] leading-relaxed text-muted-foreground">{g.a}</p>
                </div>
              ))}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
