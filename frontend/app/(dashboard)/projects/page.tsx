"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LayoutGrid, List as ListIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api/client";
import { createProject, listProjects, type Project } from "@/lib/api/projects";
import { createProjectSchema, type CreateProjectInput } from "@/lib/validation/project.schema";

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

export default function ProjectsPage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [createdProject, setCreatedProject] = useState<Project | null>(null);
  const [view, setView] = useState<"list" | "grid">("list");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["projects"],
    queryFn: () => listProjects(),
  });

  function closeDialog() {
    setDialogOpen(false);
    setCreatedProject(null);
  }

  const isEmpty = data?.items.length === 0;
  const emptyState = (
    <EmptyState
      title="No projects yet"
      description="Create one to start running SAST scans."
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
      {view === "grid" ? (
        <DataTableCard
          bare
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load projects."
          isEmpty={!!isEmpty}
          emptyState={emptyState}
        >
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data?.items.map((p) => (
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
                  <ApiKeysQuickLink projectId={p.id} />
                </CardContent>
              </Card>
            ))}
          </div>
        </DataTableCard>
      ) : (
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load projects."
          isEmpty={!!isEmpty}
          emptyState={emptyState}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Scans</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.items.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <Link href={`/projects/${p.id}`} className="font-medium underline-offset-4 hover:underline">
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
                    <ApiKeysQuickLink projectId={p.id} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      )}
    </div>
  );
}
