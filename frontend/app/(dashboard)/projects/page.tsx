"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, GitBranch, KeyRound, LayoutGrid, List as ListIcon, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { ProjectRepoBreakdown } from "@/components/projects/project-repo-breakdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api/client";
import { createProject, listProjects, type Project } from "@/lib/api/projects";
import { createProjectSchema, type CreateProjectInput } from "@/lib/validation/project.schema";

type StatusFilter = "all" | "active" | "archived";

function CreatedProjectNextSteps({ project, onDismiss }: { project: Project; onDismiss: () => void }) {
  const router = useRouter();

  return (
    <>
      <DialogHeader>
        <DialogTitle>&quot;{project.name}&quot; is ready</DialogTitle>
        <DialogDescription>
          Next: generate a project token so the ZeroStrike SAST scanner can authenticate and upload
          results for this project.
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button variant="ghost" onClick={onDismiss}>
          I&apos;ll do this later
        </Button>
        <Button
          onClick={() => {
            router.push(`/projects/${project.id}?tab=keys`);
            onDismiss();
          }}
        >
          Set up project token
        </Button>
      </DialogFooter>
    </>
  );
}

function CreateProjectForm({ onCreated }: { onCreated: (project: Project) => void }) {
  const queryClient = useQueryClient();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateProjectInput>({ resolver: zodResolver(createProjectSchema) });

  const mutation = useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Project created");
      onCreated(project);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to create project"),
  });

  return (
    <form onSubmit={handleSubmit((values) => mutation.mutate(values))}>
      <DialogHeader>
        <DialogTitle>New project</DialogTitle>
        <DialogDescription>
          A project groups the SAST scans, members, and scanner project tokens for one codebase.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name">Name</Label>
          <Input id="name" {...register("name")} />
          {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
        </div>
        <div className="space-y-2">
          <Label htmlFor="description">Description</Label>
          <Input id="description" {...register("description")} />
        </div>
      </div>
      <DialogFooter>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Creating…" : "Create project"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function ApiKeysQuickLink({ projectId }: { projectId: string }) {
  return (
    <Button
      variant="outline"
      size="sm"
      nativeButton={false}
      render={<Link href={`/projects/${projectId}?tab=keys`} />}
    >
      <KeyRound />
      Project Tokens
    </Button>
  );
}

function RepoQuickLink({ projectId }: { projectId: string }) {
  return (
    <Button
      variant="outline"
      size="sm"
      nativeButton={false}
      render={<Link href={`/projects/${projectId}?tab=repos`} />}
    >
      <GitBranch />
      Repositories
    </Button>
  );
}

function ProjectsPageContent() {
  const searchParams = useSearchParams();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [createdProject, setCreatedProject] = useState<Project | null>(null);
  const [view, setView] = useState<"list" | "grid">("list");
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const { data, isLoading, isError } = useQuery({
    queryKey: ["projects"],
    queryFn: () => listProjects(),
  });

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function closeDialog() {
    setDialogOpen(false);
    setCreatedProject(null);
  }

  const filtered = useMemo(() => {
    let items = data?.items ?? [];
    if (statusFilter !== "all") {
      items = items.filter((p) => (statusFilter === "archived" ? p.is_archived : !p.is_archived));
    }
    if (search) {
      const q = search.toLowerCase();
      items = items.filter((p) => p.name.toLowerCase().includes(q) || p.description?.toLowerCase().includes(q));
    }
    return items;
  }, [data, search, statusFilter]);

  const isEmpty = filtered.length === 0;
  const emptyState = (
    <EmptyState
      title={data?.items.length ? "No projects match your filters" : "No projects yet"}
      description={data?.items.length ? "Try a different search or status filter." : "Create one to start running SAST scans."}
    />
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Projects"
        description="Run ZeroStrike SAST scans against your codebases and review the findings."
        actions={
          <>
            <div className="flex rounded-lg border border-border p-0.5">
              <Button
                variant={view === "list" ? "secondary" : "ghost"}
                size="icon-sm"
                aria-label="List view"
                onClick={() => setView("list")}
              >
                <ListIcon />
              </Button>
              <Button
                variant={view === "grid" ? "secondary" : "ghost"}
                size="icon-sm"
                aria-label="Grid view"
                onClick={() => setView("grid")}
              >
                <LayoutGrid />
              </Button>
            </div>
            <Dialog open={dialogOpen} onOpenChange={(open) => (open ? setDialogOpen(true) : closeDialog())}>
              <DialogTrigger render={<Button>New Project</Button>} />
              <DialogContent>
                {createdProject ? (
                  <CreatedProjectNextSteps project={createdProject} onDismiss={closeDialog} />
                ) : (
                  <CreateProjectForm onCreated={setCreatedProject} />
                )}
              </DialogContent>
            </Dialog>
          </>
        }
      />

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-xs">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search projects…"
            className="pl-8"
          />
        </div>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
          <SelectTrigger size="sm" className="w-full sm:w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="archived">Archived</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {view === "grid" ? (
        <DataTableCard bare isLoading={isLoading} isError={isError} errorMessage="Failed to load projects." isEmpty={isEmpty} emptyState={emptyState}>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((p) => (
              <Card key={p.id}>
                <CardContent className="space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <Link href={`/projects/${p.id}`} className="font-medium underline-offset-4 hover:underline">
                      {p.name}
                    </Link>
                    <Badge variant="secondary" className="font-mono uppercase">
                      {p.my_role}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {p.scan_count} scan{p.scan_count === 1 ? "" : "s"} · {p.is_archived ? "Archived" : "Active"}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <RepoQuickLink projectId={p.id} />
                    <ApiKeysQuickLink projectId={p.id} />
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleExpanded(p.id)}
                    className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                  >
                    <ChevronDown className={cn("size-3.5 transition-transform", expanded.has(p.id) && "rotate-180")} />
                    Repositories
                  </button>
                  {expanded.has(p.id) && (
                    <div className="border-t border-border pt-3">
                      <ProjectRepoBreakdown projectId={p.id} />
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </DataTableCard>
      ) : (
        <DataTableCard isLoading={isLoading} isError={isError} errorMessage="Failed to load projects." isEmpty={isEmpty} emptyState={emptyState}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Scans</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((p) => (
                <Fragment key={p.id}>
                  <TableRow className="cursor-pointer" onClick={() => toggleExpanded(p.id)}>
                    <TableCell>
                      <Link
                        href={`/projects/${p.id}`}
                        className="font-medium underline-offset-4 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="font-mono uppercase">
                        {p.my_role}
                      </Badge>
                    </TableCell>
                    <TableCell>{p.scan_count}</TableCell>
                    <TableCell>{p.is_archived ? "Archived" : "Active"}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
                        <RepoQuickLink projectId={p.id} />
                        <ApiKeysQuickLink projectId={p.id} />
                      </div>
                    </TableCell>
                    <TableCell>
                      <ChevronDown
                        className={cn("size-4 text-muted-foreground transition-transform", expanded.has(p.id) && "rotate-180")}
                      />
                    </TableCell>
                  </TableRow>
                  {expanded.has(p.id) && (
                    <TableRow>
                      <TableCell colSpan={6} className="bg-muted/20 p-4">
                        <p className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                          Repositories
                        </p>
                        <ProjectRepoBreakdown projectId={p.id} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      )}
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense fallback={null}>
      <ProjectsPageContent />
    </Suspense>
  );
}
