"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { revokeApiKey, createApiKey, listApiKeys } from "@/lib/api/api-keys";
import { ApiError } from "@/lib/api/client";
import { inviteMember, listMembers, removeMember } from "@/lib/api/project-members";
import { listProjectRepos, removeProjectRepo } from "@/lib/api/project-repos";
import { getProject, updateProject } from "@/lib/api/projects";
import { listScans } from "@/lib/api/scans";
import {
  createApiKeySchema,
  inviteMemberSchema,
  type CreateApiKeyInput,
  type InviteMemberInput,
} from "@/lib/validation/project.schema";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { NewScanDialog } from "@/components/scans/new-scan-dialog";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";

function canManage(role: string | undefined) {
  return role === "owner" || role === "admin";
}

function OverviewTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { data: project } = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => getProject(projectId),
  });
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

  if (!project) return <Skeleton className="h-32 w-full" />;

  return (
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
              <dt className="text-muted-foreground">Scans run</dt>
              <dd>{project.scan_count}</dd>
              <dt className="text-muted-foreground">Last scan</dt>
              <dd>{project.last_scan_at ? new Date(project.last_scan_at).toLocaleString() : "Never"}</dd>
              <dt className="text-muted-foreground">Status</dt>
              <dd>{project.is_archived ? "Archived" : "Active"}</dd>
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
  );
}

function MembersTab({ projectId, myRole }: { projectId: string; myRole: string | undefined }) {
  const queryClient = useQueryClient();
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

  return (
    <div className="space-y-4">
      {canManage(myRole) && (
        <form
          onSubmit={handleSubmit((values) => invite.mutate(values))}
          className="flex items-end gap-2"
        >
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
      <DataTableCard
        isLoading={isLoading}
        isError={false}
        isEmpty={!!members && members.length === 0}
        emptyState={
          <EmptyState
            title="No members yet"
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
            {members?.map((m) => (
              <TableRow key={m.id}>
                <TableCell className="font-mono text-xs">{m.invited_email}</TableCell>
                <TableCell>
                  <Badge variant="secondary" className="font-mono uppercase">
                    {m.role}
                  </Badge>
                </TableCell>
                <TableCell>{m.status === "pending" ? "Pending" : "Accepted"}</TableCell>
                <TableCell>
                  {m.role !== "owner" && (
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => remove.mutate(m.id)}
                      disabled={remove.isPending}
                    >
                      Remove
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

function ScansTab({ projectId }: { projectId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["projects", projectId, "scans"],
    queryFn: () => listScans(projectId),
    // Poll while any scan is still running so cloud-scan status updates live.
    refetchInterval: (q) =>
      q.state.data?.items.some((s) => s.status === "pending" || s.status === "running") ? 3000 : false,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Local and CI/CD scans appear here once the scanner runs and uploads. Cloud scans run on the
          server — open one to watch progress and review findings.
        </p>
        <NewScanDialog projectId={projectId} />
      </div>
      <DataTableCard
        isLoading={isLoading}
        isError={false}
        isEmpty={data?.items.length === 0}
        emptyState={
          <EmptyState
            title="No scans yet"
            description="Set up a local, cloud, or CI/CD scan to get started."
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Label</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((s) => (
              <TableRow key={s.id}>
                <TableCell>
                  <ScanTypeBadge scanType={s.scan_type} />
                </TableCell>
                <TableCell>{s.scan_label || "—"}</TableCell>
                <TableCell>
                  <ScanStatusBadge status={s.status} />
                </TableCell>
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
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

function RepositoriesTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
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
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => remove.mutate(r.id)}
                    disabled={remove.isPending}
                  >
                    Disconnect
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
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
