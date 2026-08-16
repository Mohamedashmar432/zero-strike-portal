"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { revokeApiKey, createApiKey, listApiKeys } from "@/lib/api/api-keys";
import { ApiError } from "@/lib/api/client";
import { inviteMember, listMembers, removeMember, updateMemberRole } from "@/lib/api/project-members";
import { refetchWhileAnyScanOrAiActive } from "@/lib/api/polling";
import { listProjectRepos, reauthProjectRepo, removeProjectRepo } from "@/lib/api/project-repos";
import { getProject, getProjectScanActivity } from "@/lib/api/projects";
import { getProjectAiUsage } from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";
import { createCloudScan, listScans, type Scan, type ScanStatus, type ScanType } from "@/lib/api/scans";
import {
  createApiKeySchema,
  inviteMemberSchema,
  type CreateApiKeyInput,
  type InviteMemberInput,
} from "@/lib/validation/project.schema";
import { reauthRepoSchema, type ReauthRepoInput } from "@/lib/validation/repo-credential.schema";
import { DataTableCard } from "@/components/common/data-table-card";
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
import { Activity, ChevronDown, Play, ShieldAlert, Swords } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
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
  const risk = projectRiskStatus(currentCounts);
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
          caption={risk.label === "At Risk" ? "Critical vulnerabilities present" : "No critical blockers"}
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
                    <ScanTypeBadge scanType={s.scan_type} />
                  </TableCell>
                  <TableCell>{s.scan_label || "—"}</TableCell>
                  <TableCell className="max-w-48 truncate font-mono text-xs" title={repoLabel(s)}>
                    {repoLabel(s)}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <ScanStatusBadge status={s.status} />
                      <AiStatusBadge
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

function RepositoriesTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [reauthTargetId, setReauthTargetId] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });

  const remove = useMutation({
    mutationFn: (repoId: string) => removeProjectRepo(projectId, repoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
      toast.success("Repository disconnected");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to disconnect repository"),
  });

  const scan = useMutation({
    mutationFn: (repoId: string) => createCloudScan(projectId, { project_repo_id: repoId }),
    onSuccess: (createdScan) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.scans(projectId) });
      toast.success("Scan started");
      router.push(`/projects/${projectId}/scans/${createdScan.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to start scan"),
  });

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
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono text-xs">
                  {r.label ? `${r.label} — ${r.repo_full_name}` : r.repo_full_name}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary" className="font-mono uppercase">
                    {r.provider === "azure_devops" ? "Azure DevOps" : "GitHub"}
                  </Badge>
                </TableCell>
                <TableCell className="font-mono text-xs">{r.selected_branch}</TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      onClick={() => scan.mutate(r.id)}
                      disabled={scan.isPending}
                    >
                      {scan.isPending && scan.variables === r.id ? "Starting…" : "Scan"}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setReauthTargetId(r.id)}>
                      Re-authenticate
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => remove.mutate(r.id)}
                      disabled={remove.isPending}
                    >
                      Disconnect
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
      <ReauthDialog projectId={projectId} repoId={reauthTargetId} onClose={() => setReauthTargetId(null)} />
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
        Generate a project token here, then pass it to the ZeroStrike SAST scanner CLI with{" "}
        <code>--token</code>. The token alone identifies this project — no project ID needed.
      </p>
      {revealedToken && (
        <Alert className="border-amber-500/50 bg-amber-500/5">
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

  const initialTab = tabParam && TAB_VALUES.includes(tabParam) ? tabParam : "overview";
  const [activeTab, setActiveTab] = useState<string>(initialTab);

  const { data: project, isLoading: isProjectLoading } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });

  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });

  const { data: members } = useQuery({
    queryKey: queryKeys.projects.members(projectId),
    queryFn: () => listMembers(projectId),
  });

  const { data: activity } = useQuery({
    queryKey: queryKeys.projects.scanActivity(projectId),
    queryFn: () => getProjectScanActivity(projectId),
  });

  const { data: aiUsage } = useQuery({
    queryKey: queryKeys.projects.aiUsage(projectId),
    queryFn: () => getProjectAiUsage(projectId),
  });

  function handleTabChange(tabId: string) {
    setActiveTab(tabId);
    const params = new URLSearchParams(searchParams.toString());
    if (tabId === "overview") {
      params.delete("tab");
    } else {
      params.set("tab", tabId);
    }
    const query = params.toString();
    router.replace(`/projects/${projectId}${query ? `?${query}` : ""}`, { scroll: false });
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
  const risk = projectRiskStatus(currentCounts);

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
                {project.description || "ZeroStrike DevSecOps & Security Operations Hub."}
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
            {activeTab === "repos" && <RepositoriesTab projectId={projectId} />}
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
