"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Cloud, ExternalLink, GitBranch } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { listApiKeys } from "@/lib/api/api-keys";
import { ApiError } from "@/lib/api/client";
import { listProjectRepos, type ProjectRepo } from "@/lib/api/project-repos";
import { getProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import {
  createCloudScan,
  formatAlreadyScanned,
  type CiProvider,
  type CreatedScan,
  type ScanType,
} from "@/lib/api/scans";
import { cn } from "@/lib/utils";
import { newCloudScanSchema, type NewCloudScanInput } from "@/lib/validation/scan.schema";
import { RepoConnectWizard } from "@/components/repos/repo-connect-wizard";

function scannerServerOrigin(): string {
  const env = process.env.NEXT_PUBLIC_SCANNER_SERVER_ORIGIN;
  if (env) return env.replace(/\/$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return "https://your-portal";
}

const SCAN_TYPES: { value: ScanType; label: string; description: string; icon: typeof Cloud }[] = [
  { value: "cloud", label: "Cloud", description: "Give thinkShield a repo URL and it clones + scans it server-side.", icon: Cloud },
  { value: "cicd", label: "CI/CD", description: "Add thinkShield to your pipeline (GitHub Actions, GitLab CI, Azure Pipelines).", icon: GitBranch },
];

const CI_PROVIDERS: { value: CiProvider; label: string }[] = [
  { value: "github_actions", label: "GitHub Actions" },
  { value: "gitlab_ci", label: "GitLab CI" },
  { value: "azure_pipelines", label: "Azure Pipelines" },
];

function downloadTextFile(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function CopyBlock({ text, label, filename }: { text: string; label?: string; filename?: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div>{label && <Label>{label}</Label>}</div>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              navigator.clipboard.writeText(text);
              toast.success("Copied");
            }}
          >
            Copy
          </Button>
          {filename && (
            <Button type="button" size="sm" variant="outline" onClick={() => downloadTextFile(filename, text)}>
              Download
            </Button>
          )}
        </div>
      </div>
      <code className="block overflow-x-auto rounded bg-muted px-3 py-2.5 text-xs leading-relaxed whitespace-pre">
        {text}
      </code>
    </div>
  );
}

function BackToTypes({ onBack }: { onBack: () => void }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="mb-2 flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-3.5" />
      Change scan type
    </button>
  );
}

function TypeSelectStep({ onSelect }: { onSelect: (type: ScanType) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {SCAN_TYPES.map((t) => (
        <Button
          key={t.value}
          type="button"
          variant="outline"
          className="h-auto flex-col items-start gap-2 whitespace-normal p-4 text-left transition-colors hover:border-primary/50 hover:bg-accent"
          onClick={() => onSelect(t.value)}
        >
          <t.icon className="size-5 text-brand" />
          <span className="font-medium text-foreground">{t.label}</span>
          <span className="text-xs text-muted-foreground">{t.description}</span>
        </Button>
      ))}
    </div>
  );
}

// Runners for all three providers below default to Linux (ubuntu-latest / default GitLab image /
// Azure's ubuntu pool), so linux-amd64 is the only download target needed for v1. Windows/macOS
// CI runner variants are a documented future extension, not built now.
// Hardcoded to "latest" (YAGNI) — add a version param if pinning a release ever matters.
function cicdInstallLines(origin: string): string[] {
  // Verify against the portal's checksums.txt (lines are "<sha256>  zerostrike_linux_amd64") so
  // a corrupted or tampered download fails the CI step instead of running. Note this checks
  // integrity against the same server; it is not an independent signature.
  return [
    `BASE=${origin}/api/v1/downloads/zerostrike/latest`,
    'curl -fsSL "$BASE/linux-amd64" -o zerostrike_linux_amd64',
    'curl -fsSL "$BASE/checksums.txt" -o checksums.txt',
    'grep " zerostrike_linux_amd64$" checksums.txt | sha256sum -c -',
    "mv zerostrike_linux_amd64 zerostrike",
    "chmod +x ./zerostrike",
  ];
}

// What should make the pipeline fail. The scanner exits 1 when it finds anything and 2 when
// something actually broke (bad token, upload failure, crash). Each snippet treats 0 and 1 as a
// passing scan and fails only on a real error, then counts critical and high findings in the JSON
// report. By default findings only raise the provider's own red warning; the engineer opts in to
// failing the pipeline by setting ZEROSTRIKE_FAIL_ON in the YAML. The portal remains the readable
// report; the JSON file is also kept as a pipeline artifact.
const REPORT_FILE = "zerostrike-report.json";

type FailOn = "none" | "critical" | "high";

const FAIL_ON_OPTIONS: { value: FailOn; label: string; description: string }[] = [
  { value: "none", label: "Warn only", description: "Findings never fail the pipeline; critical or high ones raise a red warning." },
  { value: "critical", label: "Fail on critical", description: "The pipeline fails if any critical finding is found." },
  { value: "high", label: "Fail on critical or high", description: "The pipeline fails if any critical or high finding is found." },
];

const FAIL_ON_COMMENT = [
  "# What fails the pipeline: none = warn only, critical = fail on critical,",
  "# high = fail on critical or high.",
];

function cicdFilename(provider: CiProvider): string {
  if (provider === "github_actions") return "zerostrike.yml";
  if (provider === "gitlab_ci") return ".gitlab-ci.yml";
  return "azure-pipelines.yml";
}

/** Indents each line of a shell script so it sits under a YAML `|` block scalar. */
const block = (lines: string[], indent: number) => lines.map((l) => " ".repeat(indent) + l);

/**
 * The shared shell for the scan step. `warn` surfaces the red message ($crit / $high are set by
 * then) and `soft` runs afterwards only when the findings did not trip ZEROSTRIKE_FAIL_ON. Both run
 * only when there is something critical or high. An unrecognised ZEROSTRIKE_FAIL_ON value is
 * treated as "none".
 */
function cicdScanLines(origin: string, token: string, warn: string[], soft: string[] = []): string[] {
  return [
    "rc=0",
    "./zerostrike scan . \\",
    `  --server ${origin} \\`,
    `  --token ${token} \\`,
    `  --format json --output ${REPORT_FILE} || rc=$?`,
    // 1 = findings were found (not an error); anything higher is a genuine failure.
    'if [ "$rc" -gt 1 ]; then echo "thinkShield scan failed (exit code $rc)"; exit "$rc"; fi',
    // One "Severity" line per finding at this indent, so this does not count nested fields.
    `crit=$(grep -c '^      "Severity": "critical"' ${REPORT_FILE} || true)`,
    `high=$(grep -c '^      "Severity": "high"' ${REPORT_FILE} || true)`,
    "crit=${crit:-0}",
    "high=${high:-0}",
    'if [ "$crit" -gt 0 ] || [ "$high" -gt 0 ]; then',
    `  msg="${FINDINGS_MSG}"`,
    ...block(warn, 2),
    '  case "${ZEROSTRIKE_FAIL_ON:-none}" in',
    "    critical) blocking=$crit ;;",
    "    high) blocking=$((crit + high)) ;;",
    "    *) blocking=0 ;;",
    "  esac",
    '  if [ "$blocking" -gt 0 ]; then',
    '    echo "thinkShield: failing the pipeline (ZEROSTRIKE_FAIL_ON=$ZEROSTRIKE_FAIL_ON, $blocking blocking)"',
    "    exit 1",
    "  fi",
    ...block(soft, 2),
    "fi",
  ];
}

const FINDINGS_MSG = "thinkShield: $crit critical and $high high severity findings. See the thinkShield portal.";

function cicdSnippet(provider: CiProvider, origin: string, failOn: FailOn): string {
  const install = cicdInstallLines(origin);
  if (provider === "github_actions") {
    // ::error draws a red annotation on the run but does not fail the step.
    const scan = cicdScanLines(origin, "${{ secrets.ZEROSTRIKE_TOKEN }}", [
      'echo "::error title=thinkShield::$msg"',
    ]);
    return [
      "# .github/workflows/zerostrike.yml",
      "name: thinkShield SAST",
      "on: [push, pull_request]",
      "env:",
      ...FAIL_ON_COMMENT.map((c) => `  ${c}`),
      `  ZEROSTRIKE_FAIL_ON: ${failOn}`,
      "jobs:",
      "  zerostrike:",
      "    runs-on: ubuntu-latest",
      "    steps:",
      "      - uses: actions/checkout@v4",
      "      - name: Install thinkShield scanner",
      "        run: |",
      ...block(install, 10),
      "      - name: thinkShield scan",
      "        run: |",
      ...block(scan, 10),
      "      - name: Upload scan report",
      "        if: always()",
      "        uses: actions/upload-artifact@v4",
      "        with:",
      "          name: thinkshield-report",
      `          path: ${REPORT_FILE}`,
      "          if-no-files-found: ignore",
    ].join("\n");
  }
  if (provider === "gitlab_ci") {
    // GitLab has no annotations, so: print the message in red and exit 3, which allow_failure
    // below turns into an orange "passed with warnings" job instead of a failed pipeline. A
    // ZEROSTRIKE_FAIL_ON failure exits 1, which is not allowed to fail, so the job goes red.
    const scan = cicdScanLines(
      origin,
      "$ZEROSTRIKE_TOKEN",
      ["printf '\\033[0;31m%s\\033[0m\\n' \"$msg\""],
      ["exit 3"]
    );
    return [
      "# .gitlab-ci.yml",
      "zerostrike_scan:",
      "  stage: test",
      "  variables:",
      ...FAIL_ON_COMMENT.map((c) => `    ${c}`),
      `    ZEROSTRIKE_FAIL_ON: ${failOn}`,
      "  before_script:",
      ...install.map((l) => `    - ${l}`),
      "  script:",
      "    - |",
      ...block(scan, 6),
      "  allow_failure:",
      "    exit_codes: 3",
      "  artifacts:",
      "    when: always",
      "    paths:",
      `      - ${REPORT_FILE}`,
    ].join("\n");
  }
  // logissue type=error puts the message in the run's red error list; SucceededWithIssues keeps
  // the pipeline from failing (it shows as partially succeeded) unless ZEROSTRIKE_FAIL_ON trips
  // first, in which case the script exits 1 and the step fails.
  const scan = cicdScanLines(
    origin,
    "$(ZEROSTRIKE_TOKEN)",
    ['echo "##vso[task.logissue type=error]$msg"'],
    ['echo "##vso[task.complete result=SucceededWithIssues;]thinkShield findings"']
  );
  return [
    "# azure-pipelines.yml",
    "variables:",
    ...FAIL_ON_COMMENT.map((c) => `  ${c}`),
    `  ZEROSTRIKE_FAIL_ON: ${failOn}`,
    "steps:",
    "  - script: |",
    ...block(install, 6),
    "    displayName: Install thinkShield scanner",
    "  - script: |",
    ...block(scan, 6),
    "    displayName: thinkShield scan",
    "  - task: PublishBuildArtifacts@1",
    "    condition: always()",
    "    continueOnError: true",
    "    inputs:",
    `      PathtoPublish: ${REPORT_FILE}`,
    "      ArtifactName: thinkshield-report",
    "    displayName: Publish scan report",
  ].join("\n");
}

function CicdSetupStep({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [provider, setProvider] = useState<CiProvider>();
  const [failOn, setFailOn] = useState<FailOn>("none");
  const { data: keys, isLoading: keysLoading } = useQuery({
    queryKey: queryKeys.projects.apiKeys(projectId),
    queryFn: () => listApiKeys(projectId),
  });
  const hasToken = (keys?.items ?? []).some((k) => k.is_active);
  const noToken = !keysLoading && !hasToken;

  return (
    <div className="space-y-4">
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3",
          noToken ? "border-severity-medium bg-severity-medium-tint" : "border-border"
        )}
      >
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-sm font-medium text-foreground">Project token</p>
          <p className="text-xs text-muted-foreground">
            {keysLoading
              ? "Checking this project for a token…"
              : hasToken
                ? "This project has an active token. Store it in your CI as a secret named ZEROSTRIKE_TOKEN. The raw value is only shown once, when it is created."
                : "This project has no active token yet. Generate one, then store it in your CI as a secret named ZEROSTRIKE_TOKEN."}
          </p>
        </div>
        {/* New tab: the wizard keeps its place while the token is created. */}
        <Button
          size="sm"
          variant={noToken ? "default" : "outline"}
          nativeButton={false}
          render={<Link href={`/projects/${projectId}?tab=keys`} target="_blank" rel="noopener" />}
        >
          {noToken ? "Generate a project token" : "Manage project tokens"}
          <ExternalLink />
        </Button>
      </div>
      <div className="space-y-2">
        <Label>CI provider</Label>
        <div className="flex flex-wrap gap-1 rounded-lg border border-border p-0.5">
          {CI_PROVIDERS.map((p) => (
            <Button
              key={p.value}
              type="button"
              size="sm"
              variant={provider === p.value ? "secondary" : "ghost"}
              onClick={() => setProvider(p.value)}
            >
              {p.label}
            </Button>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        <Label>When findings are found</Label>
        <div className="flex flex-wrap gap-1 rounded-lg border border-border p-0.5">
          {FAIL_ON_OPTIONS.map((o) => (
            <Button
              key={o.value}
              type="button"
              size="sm"
              variant={failOn === o.value ? "secondary" : "ghost"}
              onClick={() => setFailOn(o.value)}
            >
              {o.label}
            </Button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          {FAIL_ON_OPTIONS.find((o) => o.value === failOn)?.description} You can change this any time by
          editing <code>ZEROSTRIKE_FAIL_ON</code> at the top of the pipeline file.
        </p>
      </div>
      {provider && (
        <div className="space-y-1">
          <CopyBlock
            label="Pipeline snippet"
            text={cicdSnippet(provider, scannerServerOrigin(), failOn)}
            filename={cicdFilename(provider)}
          />
          <p className="text-xs text-muted-foreground">
            The pipeline also fails if the scan itself errors (for example a bad token). Full results are in
            the portal, and the JSON report is kept as a pipeline artifact.
          </p>
          {provider === "github_actions" && (
            <p className="text-xs text-muted-foreground">
              Save the downloaded file as <code>.github/workflows/zerostrike.yml</code>.
            </p>
          )}
        </div>
      )}
      <div className="flex justify-end border-t border-border pt-4">
        <Button onClick={onDone}>Done</Button>
      </div>
    </div>
  );
}

function ConnectedRepoList({
  repos,
  selectedId,
  onSelect,
}: {
  repos: ProjectRepo[];
  selectedId: string;
  onSelect: (repo: ProjectRepo) => void;
}) {
  return (
    <div className="space-y-1.5">
      {repos.map((r) => (
        <button
          key={r.id}
          type="button"
          onClick={() => onSelect(r)}
          className={
            "flex w-full items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm transition-colors " +
            (selectedId === r.id
              ? "border-primary/50 bg-accent"
              : "border-border hover:border-primary/30 hover:bg-accent/50")
          }
        >
          <span className="min-w-0 flex-1 truncate font-mono text-xs">
            {r.label ? `${r.label} — ${r.repo_full_name}` : r.repo_full_name}
          </span>
          <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary" className="font-mono uppercase">
              {r.provider === "azure_devops" ? "Azure DevOps" : "GitHub"}
            </Badge>
            <code>{r.selected_branch}</code>
          </span>
        </button>
      ))}
    </div>
  );
}

function CloudCreateStep({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: projectRepos } = useQuery({
    queryKey: ["projects", projectId, "repos"],
    queryFn: () => listProjectRepos(projectId),
  });
  // "Connected" (list of repos already synced via a saved credential) is always the
  // starting point — "manual" (paste a URL + one-off token) is an opt-in fallback, not
  // the default, so the common case never requires an extra click to get there.
  const [source, setSource] = useState<"connected" | "manual">("connected");
  const [selectedRepoId, setSelectedRepoId] = useState<string>("");
  const [connectingNewRepo, setConnectingNewRepo] = useState(false);
  const hasConnectedRepos = !!projectRepos?.length;

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<NewCloudScanInput>({ resolver: zodResolver(newCloudScanSchema) });

  // Set when the server declined to queue anything: the repo head is already scanned, or a scan of
  // it is already in flight. The form stays put so "Rescan anyway" can re-submit the same input.
  const [notice, setNotice] = useState<CreatedScan | null>(null);

  const mutation = useMutation({
    mutationFn: ({ values, force }: { values: NewCloudScanInput; force?: boolean }) =>
      createCloudScan(projectId, { ...values, ...(force ? { force: true } : {}) }),
    onSuccess: (scan) => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "scans"] });
      queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
      if (scan.outcome !== "scan_queued") {
        setNotice(scan);
        return;
      }
      toast.success("Cloud scan started");
      onClose();
      router.push(`/projects/${projectId}/scans/${scan.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to start cloud scan"),
  });

  function selectConnectedRepo(repo: ProjectRepo) {
    // A notice describes the repo it was answered for; a new selection makes it stale.
    setNotice(null);
    setSelectedRepoId(repo.id);
    setValue("project_repo_id", repo.id, { shouldValidate: true });
    setValue("repo_url", undefined);
  }

  const needsRepoSelection = source === "connected" && !selectedRepoId;

  if (connectingNewRepo) {
    return (
      <RepoConnectWizard
        projectId={projectId}
        onCancel={() => setConnectingNewRepo(false)}
        onConnected={(repo) => {
          queryClient.invalidateQueries({ queryKey: ["projects", projectId, "repos"] });
          setConnectingNewRepo(false);
          setSource("connected");
          selectConnectedRepo(repo);
        }}
      />
    );
  }

  function switchToManual() {
    setNotice(null);
    setSource("manual");
    setSelectedRepoId("");
    setValue("project_repo_id", undefined);
  }

  function switchToConnected() {
    setNotice(null);
    setSource("connected");
    setValue("repo_url", undefined);
    setValue("repo_token", "");
  }

  return (
    <form
      onSubmit={handleSubmit((values) => {
        setNotice(null);
        mutation.mutate({ values });
      })}
      className="space-y-4"
    >
      <p className="text-sm text-muted-foreground">
        thinkShield clones the repository and scans it on the server.
      </p>

      {source === "connected" ? (
        <div className="space-y-2">
          <Label>Repository & branch</Label>
          {!projectRepos ? (
            <Skeleton className="h-24 w-full" />
          ) : hasConnectedRepos ? (
            <>
              <ConnectedRepoList repos={projectRepos} selectedId={selectedRepoId} onSelect={selectConnectedRepo} />
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  Need a different branch? Change it on the Repositories tab.
                </p>
                <Button type="button" variant="ghost" size="sm" onClick={() => setConnectingNewRepo(true)}>
                  + Connect a new repo
                </Button>
              </div>
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-border p-6 text-center">
              <p className="text-sm text-muted-foreground">No repositories connected to this project yet.</p>
              <Button type="button" className="mt-3" onClick={() => setConnectingNewRepo(true)}>
                Connect a repository
              </Button>
            </div>
          )}
          <button
            type="button"
            onClick={switchToManual}
            className="text-xs font-medium text-muted-foreground underline-offset-4 hover:underline"
          >
            Or scan a repo by URL instead (one-off, not saved)
          </button>
        </div>
      ) : (
        <>
          <div className="space-y-2">
            <Label htmlFor="cloud-repo">Repository URL</Label>
            <Input
              id="cloud-repo"
              placeholder="https://github.com/org/repo"
              autoComplete="off"
              {...register("repo_url", { onChange: () => setNotice(null) })}
            />
            {errors.repo_url && <p className="text-sm text-destructive">{errors.repo_url.message}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="cloud-branch">Branch (optional)</Label>
            <Input id="cloud-branch" placeholder="main" autoComplete="off" {...register("branch", { onChange: () => setNotice(null) })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cloud-token">Access token (private repos only)</Label>
            <Input id="cloud-token" type="password" autoComplete="off" {...register("repo_token")} />
          </div>
          <button
            type="button"
            onClick={switchToConnected}
            className="text-xs font-medium text-muted-foreground underline-offset-4 hover:underline"
          >
            Use a connected repo instead
          </button>
        </>
      )}
      <div className="space-y-2">
        <Label htmlFor="cloud-label">Label (optional)</Label>
        <Input id="cloud-label" autoComplete="off" {...register("scan_label")} />
      </div>
      {notice && (
        <div role="status" className="space-y-3 rounded-lg border border-border bg-muted/40 p-4 text-sm">
          {notice.outcome === "up_to_date" ? (
            <>
              <p className="font-medium">{formatAlreadyScanned(notice, notice.remote_head_sha)}</p>
              <p className="text-xs text-muted-foreground">
                The branch has not moved since the last scan, so nothing was queued.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  nativeButton={false}
                  render={<Link href={`/projects/${projectId}/scans/${notice.id}`} />}
                >
                  View results
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={mutation.isPending}
                  onClick={() =>
                    handleSubmit((values) => {
                      setNotice(null);
                      mutation.mutate({ values, force: true });
                    })()
                  }
                >
                  Rescan anyway
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="font-medium">A scan of this repository is already {notice.status}.</p>
              <Button
                type="button"
                size="sm"
                nativeButton={false}
                render={<Link href={`/projects/${projectId}/scans/${notice.id}`} />}
              >
                View running scan
              </Button>
            </>
          )}
        </div>
      )}
      <div className="flex justify-end border-t border-border pt-4">
        <Button type="submit" disabled={mutation.isPending || needsRepoSelection}>
          {mutation.isPending ? "Starting…" : "Start cloud scan"}
        </Button>
      </div>
    </form>
  );
}

export default function NewScanPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();
  const [scanType, setScanType] = useState<ScanType | null>(null);

  const { data: project } = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => getProject(projectId),
  });

  const backHref = `/projects/${projectId}?tab=scans`;
  const close = () => router.push(backHref);
  const scanTypeLabel = SCAN_TYPES.find((t) => t.value === scanType)?.label;

  return (
    <div className="space-y-6">
      <PageHeader
        title="New scan"
        description="Choose how you want to scan this project."
        breadcrumb={
          <Breadcrumbs
            items={[
              { label: "Projects", href: "/projects" },
              { label: project?.name ?? "Project", href: `/projects/${projectId}` },
              { label: "Scans", href: backHref },
              { label: "New scan" },
            ]}
          />
        }
      />
      <Card className={cn("mx-auto", scanType === "cicd" ? "max-w-5xl" : "max-w-2xl")}>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            {scanType ? `Step 2 of 2 — ${scanTypeLabel} scan` : "Step 1 of 2 — Choose scan type"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {scanType && <BackToTypes onBack={() => setScanType(null)} />}
          {scanType === "cloud" ? (
            <CloudCreateStep projectId={projectId} onClose={close} />
          ) : scanType === "cicd" ? (
            <CicdSetupStep projectId={projectId} onDone={close} />
          ) : (
            <TypeSelectStep onSelect={setScanType} />
          )}
          {!scanType && (
            <div className="mt-4 flex justify-end border-t border-border pt-4">
              <Button variant="ghost" nativeButton={false} render={<Link href={backHref} />}>
                Cancel
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
