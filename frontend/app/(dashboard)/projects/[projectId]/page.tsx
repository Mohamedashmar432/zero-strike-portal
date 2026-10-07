"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { revokeApiKey, createApiKey, listApiKeys } from "@/lib/api/api-keys";
import { ApiError, retryUnlessForbiddenOrMissing } from "@/lib/api/client";
import { inviteMember, listMembers, removeMember, updateMemberRole } from "@/lib/api/project-members";
import { refetchWhileAnyScanOrAiActive } from "@/lib/api/polling";
import {
  formatMergedPrReminder,
  formatSyncFinishedMessage,
  headCommitForSelectedBranch,
  listProjectRepos,
  reauthProjectRepo,
  refetchWhileAnyRepoSyncing,
  refreshRepoPrStatus,
  removeProjectRepo,
  shortSha,
  syncProjectRepo,
  updateProjectRepoBranch,
  type ProjectRepo,
} from "@/lib/api/project-repos";
import { getScanRegression, getVulnerabilitySummary } from "@/lib/api/vulnerabilities";
import { getProject, getProjectScanActivity, hasCompletedScan } from "@/lib/api/projects";
import { getProjectAiUsage } from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";
import { listScans, type Scan, type ScanStatus, type ScanType } from "@/lib/api/scans";
import {
  createApiKeySchema,
  inviteMemberSchema,
  type CreateApiKeyInput,
  type InviteMemberInput,
} from "@/lib/validation/project.schema";
import { reauthRepoSchema, type ReauthRepoInput } from "@/lib/validation/repo-credential.schema";
import { QueueTag } from "@/components/queue/queue-tag";
import { DataTableCard } from "@/components/common/data-table-card";
import { RelativeTime } from "@/components/common/relative-time";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Activity, ChevronDown, GitBranch, KeyRound, Loader2, Play, RefreshCw, ShieldAlert, Swords, Unplug } from "lucide-react";
import { IconAction, RowActionsMenu } from "@/components/common/row-actions";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/providers/auth-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { StatCard } from "@/components/common/stat-card";
import { ProjectSidebar } from "@/components/projects/project-sidebar";
import { ProjectOverviewHub } from "@/components/projects/project-overview-hub";
import { ProjectDastTab } from "@/components/projects/project-dast-tab";
import { ProjectAttackSimTab } from "@/components/projects/project-attack-sim-tab";
import { ProjectOwaspSection } from "@/components/projects/project-owasp-section";
import { ProjectHistoryTab } from "@/components/projects/project-history-tab";
import { AiAnalyticsDashboard } from "@/components/ai/ai-analytics-dashboard";
import { ProjectComplianceTab } from "@/components/projects/project-compliance-tab";
import { ProjectComplianceConfigTab } from "@/components/projects/project-compliance-config-tab";
import { ProjectAutoFixTab } from "@/components/projects/project-auto-fix-tab";
import { ProjectSettingsTab } from "@/components/projects/project-settings-tab";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { projectRiskStatus, SeverityCountPills } from "@/components/severity/severity-count-pills";
import { cn, getInitials, parseApiDate } from "@/lib/utils";
import { roleLabel } from "@/lib/role-labels";
import type { SeverityCounts } from "@/lib/api/dashboard";

const EMPTY_SEVERITY_COUNTS: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };

function canManage(role: string | undefined) {
  return role === "owner" || role === "admin";
}

const PROVIDER_LABELS: Record<string, string> = {
  github: "GitHub",
  azure_devops: "Azure DevOps",
};

function providerLabel(p: string) {
  return PROVIDER_LABELS[p] ?? p;
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] items-start gap-2 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function OverviewTab({ projectId }: { projectId: string }) {
  const { data: project } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });
  // Shared query key with MembersTab, so this reuses that cache instead of re-fetching.
  const { data: members } = useQuery({
    queryKey: queryKeys.projects.members(projectId),
    queryFn: () => listMembers(projectId),
  });
  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });
  const { data: activity } = useQuery({
    queryKey: queryKeys.projects.scanActivity(projectId),
    queryFn: () => getProjectScanActivity(projectId),
  });
  const { data: aiUsage } = useQuery({
    queryKey: queryKeys.projects.aiUsage(projectId),
    queryFn: () => getProjectAiUsage(projectId),
  });

  const owners = (members ?? []).filter((m) => m.role === "owner");

  if (!project) return <Skeleton className="h-32 w-full" />;

  // Risk + overall findings reflect CURRENT posture (latest scan per repo), not all-time.
  const currentCounts = activity?.current_findings ?? project.findings_by_severity ?? EMPTY_SEVERITY_COUNTS;
  const risk = projectRiskStatus(currentCounts, hasCompletedScan(activity) ? undefined : "none");
  const sources = [...new Set((repos ?? []).map((r) => providerLabel(r.provider)))];
  const connectedCount = activity?.repos.filter((g) => g.repo_id).length ?? repos?.length ?? 0;

  const aiUsageText = aiUsage?.enabled
    ? [aiUsage.active_provider, aiUsage.active_model].filter(Boolean).join(" · ") || "Enabled"
    : "Not configured";

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard
          label="Security Risk Level"
          value={<span className={cn("rounded-md px-2.5 py-0.5 text-base font-semibold", risk.className)}>{risk.label}</span>}
          caption={
            risk.label === "At Risk" ? "Critical vulnerabilities present"
            : risk.label === "Unknown" ? "No completed scan yet"
            : "No critical blockers"
          }
        />
        <StatCard label="Total Scan Executions" value={project.scan_count} caption="Across all branches & commits" />
        <StatCard
          label="Active Security Findings"
          value={activity?.current_findings_total ?? project.total_findings ?? 0}
          caption={connectedCount ? `Latest scan across ${connectedCount} repo(s)` : undefined}
          valueClassName="font-mono font-bold"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <Card className="border-border/80 bg-card/60">
            <CardHeader className="border-b border-border/60 pb-3">
              <CardTitle className="text-sm font-semibold tracking-tight">Project Metadata & Integrations</CardTitle>
            </CardHeader>
            <CardContent className="p-4">
              <dl className="divide-y divide-border/50 text-xs">
                <DetailRow label="Project Name">
                  <span className="font-semibold text-foreground">{project.name}</span>
                </DetailRow>
                <DetailRow label="Description">
                  <span className="text-muted-foreground">{project.description || "No description provided."}</span>
                </DetailRow>
                <DetailRow label="Ownership">
                  {owners.length === 0 ? (
                    "—"
                  ) : (
                    <div className="flex flex-wrap items-center gap-2">
                      {owners.map((o) => (
                        <span key={o.id} className="flex items-center gap-1.5 font-medium">
                          <Avatar size="sm" className="size-5 border border-border">
                            <AvatarFallback className="text-[10px] bg-primary/20 text-primary">
                              {getInitials(o.name ?? o.invited_email)}
                            </AvatarFallback>
                          </Avatar>
                          {o.name ?? o.invited_email}
                        </span>
                      ))}
                    </div>
                  )}
                </DetailRow>
                <DetailRow label="Lifecycle Status">
                  <Badge variant={project.is_archived ? "outline" : "secondary"} className="text-[10px] font-mono uppercase">
                    {project.is_archived ? "Archived" : "Active"}
                  </Badge>
                </DetailRow>
                <DetailRow label="Source Repositories">
                  <span className="font-mono">{sources.length ? sources.join(", ") : "No repositories connected"}</span>
                </DetailRow>
                <DetailRow label="Last Security Scan">
                  <span className="font-mono">
                    {project.last_scan_at ? parseApiDate(project.last_scan_at).toLocaleString() : "Never"}
                  </span>
                </DetailRow>
                <DetailRow label="AI Auditor Integration">
                  <span className="font-mono text-muted-foreground">{aiUsageText}</span>
                </DetailRow>
                <DetailRow label="Total AI Token Usage">
                  <span className="font-mono">
                    {aiUsage ? `${(aiUsage.total_prompt_tokens + aiUsage.total_completion_tokens).toLocaleString()} tokens` : "—"}
                  </span>
                </DetailRow>
              </dl>
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-4 space-y-4">
          <Card className="border-border/80 bg-card/60">
            <CardHeader className="border-b border-border/60 pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
                Current Findings Distribution
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 space-y-3">
              <SeverityCountPills counts={currentCounts} />
              <p className="text-[11px] text-muted-foreground">
                Aggregated latest scan results for this project.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function MembersTab({ projectId, myRole }: { projectId: string; myRole: string | undefined }) {
  const queryClient = useQueryClient();
  const { user: currentUser } = useAuth();
  const { data: members, isLoading } = useQuery({
    queryKey: queryKeys.projects.members(projectId),
    queryFn: () => listMembers(projectId),
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<InviteMemberInput>({ resolver: zodResolver(inviteMemberSchema) });

  const invite = useMutation({
    mutationFn: (values: InviteMemberInput) => inviteMember(projectId, values.email),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.members(projectId) });
      toast.success("Invite sent");
      reset();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to invite member"),
  });

  const remove = useMutation({
    mutationFn: (memberId: string) => removeMember(projectId, memberId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.members(projectId) });
      toast.success("Member removed");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to remove member"),
  });

  const updateRole = useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: "owner" | "collaborator" }) =>
      updateMemberRole(projectId, memberId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.members(projectId) });
      toast.success("Role updated");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update role"),
  });

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"pending" | "accepted">();
  const filteredMembers = (members ?? []).filter((m) => {
    if (statusFilter && m.status !== statusFilter) return false;
    if (search && !m.invited_email.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-4">
      {/* Inviting, like role changes and removing *others*, is owner/admin-gated. */}
      {canManage(myRole) && (
        <form onSubmit={handleSubmit((values) => invite.mutate(values))} className="flex items-end gap-2">
          <div className="flex-1 space-y-2">
            <Label htmlFor="invite-email">Invite by email</Label>
            <Input id="invite-email" type="email" {...register("email")} />
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>
          <Button type="submit" disabled={invite.isPending}>
            {invite.isPending ? "Inviting…" : "Invite"}
          </Button>
        </form>
      )}
      <FilterBar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="Search by email…"
        facets={[
          {
            type: "toggle",
            value: statusFilter,
            onChange: (v) => setStatusFilter(v as "pending" | "accepted" | undefined),
            options: [
              { value: "pending", label: "Pending" },
              { value: "accepted", label: "Accepted" },
            ],
          },
        ]}
      />
      <DataTableCard
        isLoading={isLoading}
        isError={false}
        isEmpty={!!members && filteredMembers.length === 0}
        emptyState={
          <EmptyState
            title={members?.length ? "No members match this filter" : "No members yet"}
            description="Invite a teammate by email to give them access to this project."
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredMembers.map((m) => {
              const isSelf = !!currentUser && m.user_id === currentUser.id;
              return (
                <TableRow key={m.id}>
                  <TableCell className="font-mono text-xs">{m.invited_email}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{roleLabel(m.role)}</Badge>
                  </TableCell>
                  <TableCell>{m.status === "pending" ? "Pending" : "Accepted"}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      {canManage(myRole) && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            updateRole.mutate({
                              memberId: m.id,
                              role: m.role === "owner" ? "collaborator" : "owner",
                            })
                          }
                          disabled={updateRole.isPending}
                        >
                          {m.role === "owner" ? "Demote" : `Promote to ${roleLabel("owner")}`}
                        </Button>
                      )}
                      {isSelf && m.role !== "owner" && (
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => remove.mutate(m.id)}
                          disabled={remove.isPending}
                        >
                          Leave
                        </Button>
                      )}
                      {!isSelf && canManage(myRole) && m.role !== "owner" && (
                        <Button
                          variant="destructive"
                          size="sm"
                          onClick={() => remove.mutate(m.id)}
                          disabled={remove.isPending}
                        >
                          Remove
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

/** Everything a finished sync can change: repos, vulnerabilities (+ summary), stats and scans. */
function invalidateSyncViews(queryClient: QueryClient, projectId: string) {
  queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
  queryClient.invalidateQueries({ queryKey: ["projects", projectId, "vulnerabilities"] });
  queryClient.invalidateQueries({ queryKey: queryKeys.projects.stats() });
  queryClient.invalidateQueries({ queryKey: queryKeys.projects.scanActivity(projectId) });
  queryClient.invalidateQueries({ queryKey: queryKeys.dashboard.stats() });
  queryClient.invalidateQueries({ queryKey: queryKeys.projects.scans(projectId) });
}

function ScansTab({ projectId }: { projectId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.projects.scans(projectId),
    queryFn: () => listScans(projectId),
    // Poll while any scan is running OR mid-AI-analysis, so both the scan status and the
    // "AI analyzing…" tag update live (a completed scan can still be enriching).
    refetchInterval: refetchWhileAnyScanOrAiActive<Scan>(),
  });

  // Shared query key with RepositoriesTab so this reuses the same cache entry.
  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });
  const repoById = new Map((repos ?? []).map((r) => [r.id, r]));
  function repoLabel(s: { project_repo_id: string | null; repo_url: string | null }) {
    const repo = s.project_repo_id ? repoById.get(s.project_repo_id) : undefined;
    if (repo) return repo.label || repo.repo_full_name;
    return s.repo_url ?? "—";
  }

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ScanStatus>();
  const [typeFilter, setTypeFilter] = useState<ScanType>();
  function matchesFilter(s: Scan) {
    if (statusFilter && s.status !== statusFilter) return false;
    if (typeFilter && s.scan_type !== typeFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!(s.scan_label ?? "").toLowerCase().includes(q) && !repoLabel(s).toLowerCase().includes(q)) {
        return false;
      }
    }
    return true;
  }
  const visibleCount = (data?.items ?? []).filter(matchesFilter).length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Local and CI/CD scans appear here once the scanner runs and uploads. Cloud scans run on the
          server — open one to watch progress and review findings.
        </p>
        <Button variant="outline" nativeButton={false} render={<Link href={`/projects/${projectId}/scans/new`} />}>
          New scan
        </Button>
      </div>
      <FilterBar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="Search by label or repo…"
        facets={[
          {
            type: "toggle",
            value: statusFilter,
            onChange: (v) => setStatusFilter(v as ScanStatus | undefined),
            options: (["pending", "queued", "running", "completed", "failed"] as ScanStatus[]).map((s) => ({
              value: s,
              label: s,
            })),
          },
          {
            type: "toggle",
            value: typeFilter,
            onChange: (v) => setTypeFilter(v as ScanType | undefined),
            options: (["local", "cloud", "cicd"] as ScanType[]).map((t) => ({ value: t, label: t })),
          },
        ]}
      />
      <DataTableCard
        isLoading={isLoading}
        isError={false}
        isEmpty={visibleCount === 0}
        emptyState={
          <EmptyState
            title={data?.items.length ? "No scans match this filter" : "No scans yet"}
            description="Set up a local, cloud, or CI/CD scan to get started."
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Label</TableHead>
              <TableHead>Repository</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Findings</TableHead>
              <TableHead>Created</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((s) => {
              if (!matchesFilter(s)) return null;
              const counts: SeverityCounts = s.findings_by_severity ?? EMPTY_SEVERITY_COUNTS;
              return (
                <TableRow key={s.id}>
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <ScanTypeBadge scanType={s.scan_type} />
                      {s.triggered_by === "sync" && (
                        <Badge variant="secondary" className="font-mono uppercase">
                          Sync
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>{s.scan_label || "—"}</TableCell>
                  <TableCell className="max-w-48 truncate font-mono text-xs" title={repoLabel(s)}>
                    {repoLabel(s)}
                    {s.git_commit && (
                      <span className="block text-muted-foreground" title={s.git_commit}>
                        {s.branch ? `${s.branch}@` : ""}
                        {shortSha(s.git_commit)}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <ScanStatusBadge status={s.status} scanId={s.id} />
                      <AiStatusBadge
                        refId={s.id}
                        status={s.ai_analysis_status}
                        startedAt={s.ai_analysis_started_at}
                        progressCompleted={s.ai_analysis_progress_completed}
                        progressTotal={s.ai_analysis_progress_total}
                      />
                    </div>
                  </TableCell>
                  <TableCell>{s.status === "completed" ? <SeverityCountPills counts={counts} /> : "—"}</TableCell>
                  <TableCell>{new Date(s.created_at).toLocaleString()}</TableCell>
                  <TableCell>
                    <Button
                      variant="outline"
                      size="sm"
                      nativeButton={false}
                      render={<Link href={`/projects/${projectId}/scans/${s.id}`} />}
                    >
                      View
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

function ReauthDialog({
  projectId,
  repoId,
  onClose,
}: {
  projectId: string;
  repoId: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ReauthRepoInput>({ resolver: zodResolver(reauthRepoSchema) });

  const reauth = useMutation({
    mutationFn: (values: ReauthRepoInput) => reauthProjectRepo(projectId, repoId!, values.pat),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
      toast.success("Repository re-authenticated");
      reset();
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to re-authenticate"),
  });

  return (
    <Dialog open={repoId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={handleSubmit((values) => reauth.mutate(values))}>
          <DialogHeader>
            <DialogTitle>Re-authenticate repository</DialogTitle>
            <DialogDescription>
              Paste a new personal access token for this repo. Only this repo&apos;s stored token is
              replaced — other connected repos are unaffected.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-4">
            <Label htmlFor="reauth-pat">Personal access token</Label>
            <Input id="reauth-pat" type="password" {...register("pat")} />
            {errors.pat && <p className="text-sm text-destructive">{errors.pat.message}</p>}
          </div>
          <DialogFooter>
            <Button type="submit" disabled={reauth.isPending}>
              {reauth.isPending ? "Verifying…" : "Re-authenticate"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ChangeBranchDialog({
  projectId,
  repo,
  onClose,
}: {
  projectId: string;
  repo: ProjectRepo | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [branch, setBranch] = useState("");
  // Re-seed whenever a different repo is opened (render-time one-shot, like the settings form).
  const [seededFor, setSeededFor] = useState<string | null>(null);
  if (repo && seededFor !== repo.id) {
    setSeededFor(repo.id);
    setBranch(repo.selected_branch);
  }

  const change = useMutation({
    mutationFn: () => updateProjectRepoBranch(projectId, repo!.id, branch.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
      toast.success("Branch changed — sync to scan it");
      setSeededFor(null);
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to change branch"),
  });

  return (
    <Dialog open={repo !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            change.mutate();
          }}
        >
          <DialogHeader>
            <DialogTitle>Change branch</DialogTitle>
            <DialogDescription>
              Syncs and cloud scans of {repo?.label || repo?.repo_full_name} will use this branch. The
              remembered head is cleared, so the next sync scans the new branch.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-4">
            <Label htmlFor="change-branch">Branch</Label>
            <Input
              id="change-branch"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
            />
          </div>
          <DialogFooter>
            <Button
              type="submit"
              disabled={change.isPending || !branch.trim() || branch.trim() === repo?.selected_branch}
            >
              {change.isPending ? "Saving…" : "Change branch"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RepositoriesTab({
  projectId,
  isArchived,
  canChangeBranch,
}: {
  projectId: string;
  isArchived: boolean;
  canChangeBranch: boolean;
}) {
  const queryClient = useQueryClient();
  const [reauthTargetId, setReauthTargetId] = useState<string | null>(null);
  const [branchTarget, setBranchTarget] = useState<ProjectRepo | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
    // Poll while any repo has a queued/running sync scan so the row leaves "Syncing" by itself.
    refetchInterval: refetchWhileAnyRepoSyncing(),
  });
  const { data: summary } = useQuery({
    queryKey: queryKeys.projects.vulnerabilitySummary(projectId),
    queryFn: () => getVulnerabilitySummary(projectId),
  });

  // A sync that finished since the last poll: refresh everything it touched and say so.
  // Tracks the previous sync_state per repo so loading the page on an idle repo stays quiet.
  const prevSync = useRef<Map<string, ProjectRepo["sync_state"]>>(new Map());
  // The scan a repo's sync is running, remembered while "syncing" so its counts can be read after.
  const syncScanId = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    if (!data) return;
    let finished = false;
    for (const r of data) {
      if (prevSync.current.get(r.id) === "syncing" && r.sync_state !== "syncing") {
        finished = true;
        if (r.sync_state === "error") {
          toast.error(
            `Sync of ${r.label || r.repo_full_name} failed${r.last_sync_error ? `: ${r.last_sync_error}` : ""}`
          );
        } else {
          const name = r.label || r.repo_full_name;
          const scanId = syncScanId.current.get(r.id);
          const generic = () => toast.success(`Sync of ${name} finished`);
          if (!scanId) generic();
          else {
            getScanRegression(projectId, scanId)
              .then((reg) => {
                toast.success(formatSyncFinishedMessage(name, reg));
              })
              .catch(generic);
          }
        }
      }
      if (r.sync_state === "syncing" && r.active_scan_id) syncScanId.current.set(r.id, r.active_scan_id);
      prevSync.current.set(r.id, r.sync_state);
    }
    if (finished) invalidateSyncViews(queryClient, projectId);
  }, [data, queryClient, projectId]);

  // Once per visit, re-read the state of any repo's open auto-fix PRs so a PR merged on the
  // provider shows up as the "merged since last sync" reminder without a Sync first. The server
  // skips a PR read in the last minute, so revisiting the tab costs no provider calls. Failures are
  // stored per PR server-side; nothing here to toast about.
  const prChecked = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!data) return;
    const pending = data.filter((r) => r.autofix_open_prs > 0 && !prChecked.current.has(r.id));
    if (!pending.length) return;
    for (const r of pending) prChecked.current.add(r.id);
    Promise.allSettled(pending.map((r) => refreshRepoPrStatus(projectId, r.id))).then((results) => {
      if (results.some((x) => x.status === "fulfilled" && x.value.newly_merged > 0)) {
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
      }
    });
  }, [data, queryClient, projectId]);

  const remove = useMutation({
    mutationFn: (repoId: string) => removeProjectRepo(projectId, repoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
      toast.success("Repository disconnected");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to disconnect repository"),
  });

  const sync = useMutation({
    mutationFn: ({ repoId, force }: { repoId: string; force?: boolean }) =>
      syncProjectRepo(projectId, repoId, force ?? false),
    onSuccess: (res, { repoId }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
      if (res.outcome === "up_to_date") {
        toast.success(`Already up to date at ${shortSha(res.remote_head_sha)}`, {
          action: { label: "Rescan anyway", onClick: () => runSync({ repoId, force: true }) },
        });
      } else if (res.outcome === "already_syncing") {
        toast.info("A sync is already running for this repository");
      } else {
        toast.success("Sync started");
        if (res.scan_id) syncScanId.current.set(repoId, res.scan_id);
        queryClient.invalidateQueries({ queryKey: queryKeys.projects.scans(projectId) });
      }
    },
    onError: (err) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
      toast.error(err instanceof ApiError ? err.message : "Failed to sync repository");
    },
  });

  // A double-click lands two clicks before React re-renders the button as disabled; without this the
  // second one reached the API and surfaced a spurious "already in progress" error toast.
  const syncInFlight = useRef(false);
  const runSync = (vars: { repoId: string; force?: boolean }) => {
    if (syncInFlight.current) return;
    syncInFlight.current = true;
    sync.mutate(vars, { onSettled: () => { syncInFlight.current = false; } });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Connect a repo here so cloud scans can reuse it without re-entering a URL or token each time. A
          project can hold multiple repos.
        </p>
        <Button variant="outline" nativeButton={false} render={<Link href={`/projects/${projectId}/repos/new`} />}>
          Add repository
        </Button>
      </div>
      <DataTableCard
        isLoading={isLoading}
        isError={false}
        isEmpty={!!data && data.length === 0}
        emptyState={
          <EmptyState
            title="No repositories connected"
            description="Connect a GitHub or Azure DevOps repo to reuse it for cloud scans."
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Repo</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Branch</TableHead>
              <TableHead>Head</TableHead>
              <TableHead>Last synced</TableHead>
              <TableHead>Open / Fixed</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((r) => {
              const counts = summary?.by_repo[r.id];
              const syncing =
                r.sync_state === "syncing" || (sync.isPending && sync.variables?.repoId === r.id);
              const mergedReminder = formatMergedPrReminder(r.autofix_merged_since_sync);
              return (
              <TableRow key={r.id}>
                <TableCell className="font-mono text-xs">
                  {r.label ? `${r.label} — ${r.repo_full_name}` : r.repo_full_name}
                  {/* A reminder, not an auto-scan: nothing scans without a user action. */}
                  {mergedReminder && !syncing && (
                    <div className="mt-1 flex items-center gap-1 font-sans text-muted-foreground">
                      <span>{mergedReminder} —</span>
                      <button
                        type="button"
                        className="text-primary underline-offset-4 hover:underline disabled:opacity-50"
                        onClick={() => runSync({ repoId: r.id })}
                        disabled={isArchived}
                      >
                        Sync now
                      </button>
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary" className="font-mono uppercase">
                    {r.provider === "azure_devops" ? "Azure DevOps" : "GitHub"}
                  </Badge>
                </TableCell>
                <TableCell className="font-mono text-xs">{r.selected_branch}</TableCell>
                <TableCell className="font-mono text-xs">
                  {r.sync_state === "behind" && headCommitForSelectedBranch(r) ? (
                    <span title="The remote branch has commits that were not scanned yet">
                      {shortSha(r.scanned_commit)} → {shortSha(r.remote_head_sha)}
                    </span>
                  ) : headCommitForSelectedBranch(r) ? (
                    shortSha(r.scanned_commit)
                  ) : (
                    <span
                      className="text-muted-foreground"
                      title={r.scanned_commit ? "Not synced on this branch" : undefined}
                    >
                      —
                    </span>
                  )}
                  {r.sync_state === "behind" && (
                    <Badge variant="secondary" className="ml-2 font-mono uppercase">
                      Behind
                    </Badge>
                  )}
                  {/* A sync waiting for a cloud-scan slot says so, with its place and countdown. */}
                  {r.sync_state === "syncing" && r.active_scan_id && (
                    <QueueTag kind="cloud_scan" refId={r.active_scan_id} standalone className="ml-2" />
                  )}
                </TableCell>
                <TableCell className="text-xs">
                  {r.last_synced_at ? (
                    <RelativeTime iso={r.last_synced_at} />
                  ) : (
                    <span className="text-muted-foreground">Never</span>
                  )}
                </TableCell>
                <TableCell className="text-xs">
                  {counts ? (
                    <Link
                      href={`/projects/${projectId}/vulnerabilities?repo=${r.id}`}
                      className="font-mono underline-offset-4 hover:underline hover:text-primary"
                    >
                      {counts.open + counts.in_progress + counts.reopened} / {counts.fixed}
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    <IconAction
                      variant="outline"
                      onClick={() => runSync({ repoId: r.id })}
                      disabled={syncing || isArchived}
                      label={
                        syncing
                          ? "Syncing…"
                          : isArchived
                          ? "This project is archived — restore it to sync"
                          : r.sync_state === "error" && r.last_sync_error
                          ? `Retry sync — ${r.last_sync_error}`
                          : "Sync — check the remote branch and scan anything new"
                      }
                    >
                      {syncing ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                    </IconAction>
                    <RowActionsMenu label={`Actions for ${r.repo_full_name}`}>
                      {canChangeBranch && (
                        <DropdownMenuItem onClick={() => setBranchTarget(r)}>
                          <GitBranch /> Change branch
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuItem onClick={() => setReauthTargetId(r.id)}>
                        <KeyRound /> Re-authenticate
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        variant="destructive"
                        onClick={() => remove.mutate(r.id)}
                        disabled={remove.isPending}
                      >
                        <Unplug /> Disconnect
                      </DropdownMenuItem>
                    </RowActionsMenu>
                  </div>
                </TableCell>
              </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </DataTableCard>
      <ReauthDialog projectId={projectId} repoId={reauthTargetId} onClose={() => setReauthTargetId(null)} />
      <ChangeBranchDialog projectId={projectId} repo={branchTarget} onClose={() => setBranchTarget(null)} />
    </div>
  );
}

function ApiKeysTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [revealedToken, setRevealedToken] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.projects.apiKeys(projectId),
    queryFn: () => listApiKeys(projectId),
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CreateApiKeyInput>({
    resolver: zodResolver(createApiKeySchema),
    defaultValues: { expires_in_days: 90 },
  });

  const create = useMutation({
    mutationFn: (values: CreateApiKeyInput) => createApiKey(projectId, values),
    onSuccess: (key) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.apiKeys(projectId) });
      setRevealedToken(key.raw_token);
      reset({ expires_in_days: 90 });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to create project token"),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.apiKeys(projectId) });
      toast.success("Project token revoked");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to revoke project token"),
  });

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Generate a project token here, then pass it to the thinkShield SAST scanner CLI with{" "}
        <code>--token</code>. The token alone identifies this project — no project ID needed.
      </p>
      {revealedToken && (
        <Alert className="border-severity-medium/50 bg-severity-medium/5">
          <AlertTitle>Copy this token now — you won&apos;t be able to see it again.</AlertTitle>
          <AlertDescription>
            <div className="flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-muted px-2 py-1 text-xs">{revealedToken}</code>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  navigator.clipboard.writeText(revealedToken);
                  toast.success("Copied to clipboard");
                }}
              >
                Copy
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setRevealedToken(null)}>
                Dismiss
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}
      <form onSubmit={handleSubmit((values) => create.mutate(values))} className="flex items-end gap-2">
        <div className="space-y-2">
          <Label htmlFor="key-label">Label</Label>
          <Input id="key-label" {...register("label")} />
          {errors.label && <p className="text-sm text-destructive">{errors.label.message}</p>}
        </div>
        <div className="space-y-2">
          <Label htmlFor="key-expiry">Expires in (days)</Label>
          <Input
            id="key-expiry"
            type="number"
            {...register("expires_in_days", { valueAsNumber: true })}
          />
        </div>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Generating…" : "Generate token"}
        </Button>
      </form>
      <DataTableCard
        isLoading={isLoading}
        isError={false}
        isEmpty={data?.items.length === 0}
        emptyState={
          <EmptyState
            title="No project tokens yet"
            description="Generate one below so the scanner can authenticate and upload results."
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Label</TableHead>
              <TableHead>Prefix</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead>Status</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((k) => (
              <TableRow key={k.id}>
                <TableCell>{k.label}</TableCell>
                <TableCell className="font-mono text-xs">{k.prefix}…</TableCell>
                <TableCell>{new Date(k.expires_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <Badge variant={k.is_active ? "secondary" : "outline"}>
                    {k.is_active ? "Active" : k.revoked_at ? "Revoked" : "Expired"}
                  </Badge>
                </TableCell>
                <TableCell>
                  {k.is_active && (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => revoke.mutate(k.id)}
                      disabled={revoke.isPending}
                    >
                      Revoke
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const TAB_VALUES = [
    "overview",
    "scans",
    "dast",
    "attack-sim",
    "history",
    "compliance",
    "compliance-config",
    "owasp",
    "auto-fix",
    "ai-usage",
    "repos",
    "members",
    "keys",
    "settings",
  ];

  // Derived from the URL, not held in state. This page never remounts on a same-route
  // navigation, so a `?tab=…` link from inside it (Compliance → Configure) changed the URL
  // and left the old tab rendered while the state was the source of truth.
  const activeTab = tabParam && TAB_VALUES.includes(tabParam) ? tabParam : "overview";

  const {
    data: project,
    isLoading: isProjectLoading,
    error: projectError,
  } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
    retry: retryUnlessForbiddenOrMissing,
  });

  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
    // A 403/404 on the project means every project-scoped call would fail the same way.
    enabled: !!project,
  });

  const { data: members } = useQuery({
    queryKey: queryKeys.projects.members(projectId),
    queryFn: () => listMembers(projectId),
    enabled: !!project,
  });

  const { data: activity } = useQuery({
    queryKey: queryKeys.projects.scanActivity(projectId),
    queryFn: () => getProjectScanActivity(projectId),
    enabled: !!project,
  });

  const { data: aiUsage } = useQuery({
    queryKey: queryKeys.projects.aiUsage(projectId),
    queryFn: () => getProjectAiUsage(projectId),
    enabled: !!project,
  });

  function handleTabChange(tabId: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (tabId === "overview") {
      params.delete("tab");
    } else {
      params.set("tab", tabId);
    }
    const query = params.toString();
    router.replace(`/projects/${projectId}${query ? `?${query}` : ""}`, { scroll: false });
  }

  if (projectError && !project) {
    const status = projectError instanceof ApiError ? projectError.status : null;
    return (
      <div className="space-y-4">
        <EmptyState
          title={
            status === 403
              ? "You don't have access to this project"
              : status === 404
                ? "Project not found"
                : "Couldn't load this project"
          }
          description={
            status === 403
              ? "Ask a project owner to add you as a member."
              : status === 404
                ? "It may have been deleted, or the link is wrong."
                : (projectError as Error).message
          }
        />
        <div className="flex justify-center">
          <Button variant="outline" nativeButton={false} render={<Link href="/projects" />}>
            Back to Projects
          </Button>
        </div>
      </div>
    );
  }

  if (isProjectLoading || !project) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-44 w-full rounded-2xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  const currentCounts: SeverityCounts =
    activity?.current_findings ??
    project.findings_by_severity ?? {
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      info: 0,
    };
  const risk = projectRiskStatus(currentCounts, hasCompletedScan(activity) ? undefined : "none");

  return (
    <div className="space-y-4">
      {/* Breadcrumb Navigation */}
      <Breadcrumbs
        items={[{ label: "Projects", href: "/projects" }, { label: project.name }]}
      />

      {/* Azure-Style Two-Tier Workspace: Secondary Project Sidebar Blade (Left) + Content (Right) */}
      <div className="flex flex-col gap-5 lg:flex-row items-start">
        {/* Left Column: Project Sidebar Blade */}
        <div className="w-full lg:w-56 lg:sticky lg:top-4 shrink-0">
          <ProjectSidebar
            project={project}
            activity={activity}
            activeTab={activeTab}
            onTabChange={handleTabChange}
            counts={{
              scans: project.scan_count,
              repos: repos?.length,
              members: members?.length,
            }}
          />
        </div>

        {/* Right Column: Main Module Work Area */}
        <div className="min-w-0 flex-1 space-y-5 w-full">
          {/* Slim Contextual Header */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-border/60 pb-3">
            <div className="space-y-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-foreground truncate">
                  {project.name}
                </h1>
                <Badge variant="secondary" className="font-mono text-[10px] uppercase">
                  {roleLabel(project.my_role)}
                </Badge>
                <Badge variant="outline" className={cn("font-mono text-[10px] uppercase", risk.className)}>
                  {risk.label}
                </Badge>
                {project.is_archived && (
                  <Badge variant="outline" className="text-[10px] text-muted-foreground uppercase font-mono">
                    Archived
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground line-clamp-1">
                {project.description || "thinkShield DevSecOps & Security Operations Hub."}
              </p>
            </div>
          </div>

          {/* Module View Content */}
          <div>
            {activeTab === "overview" && (
              <ProjectOverviewHub
                project={project}
                activity={activity}
                repos={repos}
                aiUsage={aiUsage}
                onNavigateTab={handleTabChange}
              />
            )}
            {activeTab === "scans" && <ScansTab projectId={projectId} />}
            {activeTab === "dast" && <ProjectDastTab projectId={projectId} />}
            {activeTab === "attack-sim" && <ProjectAttackSimTab projectId={projectId} />}
            {activeTab === "history" && <ProjectHistoryTab projectId={projectId} />}
            {activeTab === "compliance" && <ProjectComplianceTab projectId={projectId} />}
            {activeTab === "compliance-config" && (
              <ProjectComplianceConfigTab projectId={projectId} />
            )}
            {activeTab === "owasp" && (
              <Card className="border-border/80 bg-card/60 p-4">
                <CardHeader className="px-0 pt-0 pb-3">
                  <CardTitle className="text-sm font-semibold tracking-tight text-foreground">
                    OWASP Top 10 Risk Radar
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-0 pb-0">
                  <ProjectOwaspSection projectId={projectId} />
                </CardContent>
              </Card>
            )}
            {activeTab === "auto-fix" && (
              <ProjectAutoFixTab projectId={projectId} canApprove={canManage(project?.my_role)} />
            )}
            {activeTab === "ai-usage" && (
              <AiAnalyticsDashboard scope="project" projectId={projectId} />
            )}
            {activeTab === "repos" && (
              <RepositoriesTab
                projectId={projectId}
                isArchived={project.is_archived}
                canChangeBranch={canManage(project.my_role)}
              />
            )}
            {activeTab === "members" && (
              <MembersTab projectId={projectId} myRole={project?.my_role} />
            )}
            {activeTab === "keys" && <ApiKeysTab projectId={projectId} />}
            {activeTab === "settings" && <ProjectSettingsTab projectId={projectId} />}
          </div>
        </div>
      </div>
    </div>
  );
}
