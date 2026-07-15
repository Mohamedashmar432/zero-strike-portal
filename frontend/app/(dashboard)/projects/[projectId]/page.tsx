"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { revokeApiKey, createApiKey, listApiKeys } from "@/lib/api/api-keys";
import { ApiError } from "@/lib/api/client";
import { inviteMember, listMembers, removeMember, updateMemberRole } from "@/lib/api/project-members";
import { listProjectRepos, reauthProjectRepo, removeProjectRepo } from "@/lib/api/project-repos";
import { deleteProject, getProject, updateProject } from "@/lib/api/projects";
import { getReport } from "@/lib/api/reports";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/providers/auth-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { StatCard } from "@/components/common/stat-card";
import { RepoScanTrendChart } from "@/components/projects/repo-scan-trend-chart";
import { ProjectOwaspSection } from "@/components/projects/project-owasp-section";
import {
  ReportTemplatePicker,
  type ReportTemplateValue,
} from "@/components/reports/report-template-picker";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { projectRiskStatus, SeverityCountPills } from "@/components/severity/severity-count-pills";
import { cn, getInitials } from "@/lib/utils";
import type { SeverityCounts } from "@/lib/api/dashboard";

const EMPTY_SEVERITY_COUNTS: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };

function canManage(role: string | undefined) {
  return role === "owner" || role === "admin";
}

function OverviewTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { data: project } = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => getProject(projectId),
  });
  // Shared query key with MembersTab, so this reuses that cache instead of re-fetching.
  const { data: members } = useQuery({
    queryKey: ["projects", projectId, "members"],
    queryFn: () => listMembers(projectId),
  });
  const owners = (members ?? []).filter((m) => m.role === "owner");

  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [editing, setEditing] = useState(false);

  const mutation = useMutation({
    mutationFn: () => updateProject(projectId, { name, description }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
      toast.success("Project updated");
      setEditing(false);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update project"),
  });

  const updateTemplate = useMutation({
    mutationFn: (template: ReportTemplateValue) => updateProject(projectId, { report_template: template }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
      toast.success("Report template updated");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update report template"),
  });

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const deleteMutation = useMutation({
    mutationFn: () => deleteProject(projectId),
    onSuccess: () => {
      toast.success("Project deleted");
      router.push("/projects");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to delete project"),
  });

  if (!project) return <Skeleton className="h-32 w-full" />;

  const risk = projectRiskStatus(project.findings_by_severity ?? EMPTY_SEVERITY_COUNTS);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Overview</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {editing ? (
            <>
              <div className="space-y-2">
                <Label htmlFor="p-name">Name</Label>
                <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="p-desc">Description</Label>
                <Input id="p-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
              <div className="flex gap-2">
                <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
                  {mutation.isPending ? "Saving…" : "Save"}
                </Button>
                <Button variant="ghost" onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">{project.description || "No description."}</p>
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <dt className="text-muted-foreground">Last scan</dt>
                <dd>{project.last_scan_at ? new Date(project.last_scan_at).toLocaleString() : "Never"}</dd>
                <dt className="text-muted-foreground">Status</dt>
                <dd>{project.is_archived ? "Archived" : "Active"}</dd>
                <dt className="text-muted-foreground">Owners</dt>
                <dd>
                  {owners.length === 0 ? (
                    "—"
                  ) : (
                    <div className="flex flex-wrap items-center gap-2">
                      {owners.map((o) => (
                        <span key={o.id} className="flex items-center gap-1.5">
                          <Avatar size="sm">
                            <AvatarFallback>{getInitials(o.name ?? o.invited_email)}</AvatarFallback>
                          </Avatar>
                          {o.name ?? o.invited_email}
                        </span>
                      ))}
                    </div>
                  )}
                </dd>
              </dl>
              {canManage(project.my_role) && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setName(project.name);
                    setDescription(project.description ?? "");
                    setEditing(true);
                  }}
                >
                  Edit
                </Button>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard
          label="Risk Level"
          value={<span className={cn("rounded-sm px-2 py-0.5 text-lg", risk.className)}>{risk.label}</span>}
        />
        <StatCard label="Total Scans" value={project.scan_count} />
        <StatCard label="Overall Findings" value={project.total_findings ?? 0} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">Scan History by Repository</CardTitle>
        </CardHeader>
        <CardContent>
          <RepoScanTrendChart projectId={projectId} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">OWASP Top 10 Compliance</CardTitle>
        </CardHeader>
        <CardContent>
          <ProjectOwaspSection projectId={projectId} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">Report Template</CardTitle>
        </CardHeader>
        <CardContent>
          <ReportTemplatePicker
            value={(project.report_template ?? "inherit") as ReportTemplateValue}
            onChange={(v) => updateTemplate.mutate(v)}
            allowInherit
          />
        </CardContent>
      </Card>

      {canManage(project.my_role) && (
        <Card className="border-destructive/30">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-destructive">Danger Zone</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center justify-between gap-4">
            <p className="text-sm text-muted-foreground">
              Permanently delete this project, along with its scans, findings, and reports. This cannot be
              undone.
            </p>
            <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
              Delete Project
            </Button>
          </CardContent>
        </Card>
      )}

      <Dialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          setDeleteDialogOpen(open);
          if (!open) setConfirmName("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete project</DialogTitle>
            <DialogDescription>
              This permanently deletes <strong>{project.name}</strong> and all its scans, findings, and
              reports. This cannot be undone. Type <strong>{project.name}</strong> below to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="confirm-project-name">Project name</Label>
            <Input
              id="confirm-project-name"
              value={confirmName}
              onChange={(e) => setConfirmName(e.target.value)}
              autoComplete="off"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={confirmName !== project.name || deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
            >
              {deleteMutation.isPending ? "Deleting…" : "Delete Project"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function MembersTab({ projectId, myRole }: { projectId: string; myRole: string | undefined }) {
  const queryClient = useQueryClient();
  const { user: currentUser } = useAuth();
  const { data: members, isLoading } = useQuery({
    queryKey: ["projects", projectId, "members"],
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
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "members"] });
      toast.success("Invite sent");
      reset();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to invite member"),
  });

  const remove = useMutation({
    mutationFn: (memberId: string) => removeMember(projectId, memberId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "members"] });
      toast.success("Member removed");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to remove member"),
  });

  const updateRole = useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: "owner" | "collaborator" }) =>
      updateMemberRole(projectId, memberId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "members"] });
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
      {/* Any member can invite — only role changes and removing *others* are owner/admin-gated below. */}
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
                    <Badge variant="secondary" className="font-mono uppercase">
                      {m.role}
                    </Badge>
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
                          {m.role === "owner" ? "Demote" : "Promote to owner"}
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
    queryKey: ["projects", projectId, "scans"],
    queryFn: () => listScans(projectId),
    // Poll while any scan is still running so cloud-scan status updates live.
    refetchInterval: (q) =>
      q.state.data?.items.some((s) => s.status === "pending" || s.status === "running") ? 3000 : false,
  });

  // Shared query key with RepositoriesTab so this reuses the same cache entry.
  const { data: repos } = useQuery({
    queryKey: ["projects", projectId, "repos"],
    queryFn: () => listProjectRepos(projectId),
  });
  const repoById = new Map((repos ?? []).map((r) => [r.id, r]));
  function repoLabel(s: { project_repo_id: string | null; repo_url: string | null }) {
    const repo = s.project_repo_id ? repoById.get(s.project_repo_id) : undefined;
    if (repo) return repo.label || repo.repo_full_name;
    return s.repo_url ?? "—";
  }

  const reportQueries = useQueries({
    queries: (data?.items ?? []).map((s) => ({
      queryKey: ["scans", s.id, "report"],
      queryFn: () => getReport(s.id),
      enabled: s.status === "completed",
      retry: false,
    })),
  });

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
            {data?.items.map((s, i) => {
              if (!matchesFilter(s)) return null;
              const stats = reportQueries[i]?.data?.stats.by_severity;
              const counts: SeverityCounts = stats
                ? {
                    critical: stats.critical ?? 0,
                    high: stats.high ?? 0,
                    medium: stats.medium ?? 0,
                    low: stats.low ?? 0,
                    info: stats.info ?? 0,
                  }
                : EMPTY_SEVERITY_COUNTS;
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
                    <ScanStatusBadge status={s.status} />
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
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "repos"] });
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
    queryKey: ["projects", projectId, "repos"],
    queryFn: () => listProjectRepos(projectId),
  });

  const remove = useMutation({
    mutationFn: (repoId: string) => removeProjectRepo(projectId, repoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "repos"] });
      toast.success("Repository disconnected");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to disconnect repository"),
  });

  const scan = useMutation({
    mutationFn: (repoId: string) => createCloudScan(projectId, { project_repo_id: repoId }),
    onSuccess: (createdScan) => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "scans"] });
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
    queryKey: ["projects", projectId, "apiKeys"],
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
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "apiKeys"] });
      setRevealedToken(key.raw_token);
      reset({ expires_in_days: 90 });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to create project token"),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeApiKey(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "apiKeys"] });
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
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const initialTab =
    tabParam === "keys" || tabParam === "members" || tabParam === "scans" || tabParam === "repos"
      ? tabParam
      : "overview";
  const { data: project } = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => getProject(projectId),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title={project?.name ?? "Project"}
        breadcrumb={
          <Breadcrumbs
            items={[{ label: "Projects", href: "/projects" }, { label: project?.name ?? "Project" }]}
          />
        }
        actions={
          project && (
            <Badge variant="secondary" className="font-mono uppercase">
              {project.my_role}
            </Badge>
          )
        }
      />
      <Tabs defaultValue={initialTab}>
        <TabsList variant="line">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="scans">Scans</TabsTrigger>
          <TabsTrigger value="repos">Repositories</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
          <TabsTrigger value="keys">Project Tokens</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab projectId={projectId} />
        </TabsContent>
        <TabsContent value="scans">
          <ScansTab projectId={projectId} />
        </TabsContent>
        <TabsContent value="repos">
          <RepositoriesTab projectId={projectId} />
        </TabsContent>
        <TabsContent value="members">
          <MembersTab projectId={projectId} myRole={project?.my_role} />
        </TabsContent>
        <TabsContent value="keys">
          <ApiKeysTab projectId={projectId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
