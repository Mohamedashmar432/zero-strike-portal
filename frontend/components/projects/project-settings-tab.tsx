"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { deleteProject, getProject, updateProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import { ProjectAiProviderCard } from "@/components/projects/project-ai-provider-card";
import { ProjectPolicyCard } from "@/components/projects/project-policy-card";
import { ReportTemplatePicker, type ReportTemplateValue } from "@/components/reports/report-template-picker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

function canManage(role: string | undefined) {
  return role === "owner" || role === "admin";
}

export function ProjectSettingsTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { data: project } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [initialized, setInitialized] = useState(false);
  // Seed the form once the project loads (no effect needed — render-time one-shot).
  if (project && !initialized) {
    setName(project.name);
    setDescription(project.description ?? "");
    setInitialized(true);
  }

  const save = useMutation({
    mutationFn: () => updateProject(projectId, { name, description }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) });
      toast.success("Project updated");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update project"),
  });

  const updateTemplate = useMutation({
    mutationFn: (template: ReportTemplateValue) => updateProject(projectId, { report_template: template }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) });
      toast.success("Report template updated");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update report template"),
  });

  const [archiveDialogOpen, setArchiveDialogOpen] = useState(false);
  const setArchived = useMutation({
    mutationFn: (isArchived: boolean) => updateProject(projectId, { is_archived: isArchived }),
    onSuccess: (_res, isArchived) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.all() });
      toast.success(isArchived ? "Project archived" : "Project restored");
      setArchiveDialogOpen(false);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update project"),
  });

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const deleteMutation = useMutation({
    mutationFn: () => deleteProject(projectId),
    onSuccess: () => {
      toast.success("Project deleted");
      router.push("/projects");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to delete project"),
  });

  if (!project) return <Skeleton className="h-64 w-full" />;
  if (!canManage(project.my_role)) {
    return <p className="text-sm text-muted-foreground">You need owner or admin access to manage settings.</p>;
  }

  const deleteCommand = `sudo rm -rf ${project.name}`;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">Project settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="s-name">Name</Label>
            <Input id="s-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="s-desc">Description</Label>
            <Input id="s-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !name.trim()}>
            {save.isPending ? "Saving…" : "Save changes"}
          </Button>
        </CardContent>
      </Card>

      <ProjectAiProviderCard projectId={projectId} canManage={canManage(project.my_role)} />

      <ProjectPolicyCard projectId={projectId} />

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

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">Archive</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            {project.is_archived
              ? "This project is archived: repository syncs are disabled. Restore it to sync again."
              : "Archiving disables repository syncs. Scans, findings and reports are kept, and you can restore it at any time."}
          </p>
          {project.is_archived ? (
            <Button variant="outline" onClick={() => setArchived.mutate(false)} disabled={setArchived.isPending}>
              {setArchived.isPending ? "Restoring…" : "Restore project"}
            </Button>
          ) : (
            <Button variant="outline" onClick={() => setArchiveDialogOpen(true)}>
              Archive project
            </Button>
          )}
        </CardContent>
      </Card>

      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle className="text-sm font-medium text-destructive">Danger Zone</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            Permanently delete this project, along with its scans, findings, and reports. This cannot be undone.
          </p>
          <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
            Delete Project
          </Button>
        </CardContent>
      </Card>

      <Dialog open={archiveDialogOpen} onOpenChange={setArchiveDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archive project</DialogTitle>
            <DialogDescription>
              Archive <strong>{project.name}</strong>? Repository syncs will be disabled until it is
              restored. Nothing is deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => setArchived.mutate(true)} disabled={setArchived.isPending}>
              {setArchived.isPending ? "Archiving…" : "Archive"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteDialogOpen}
        onOpenChange={(open) => {
          setDeleteDialogOpen(open);
          if (!open) setConfirmText("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete project</DialogTitle>
            <DialogDescription>
              This permanently deletes <strong>{project.name}</strong> and all its scans, findings, and reports.
              There is no undo. Run the command below to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <p className="rounded-sm border border-sidebar-border bg-sidebar px-3 py-2 font-mono text-[13px] text-sidebar-foreground">
              <span className="select-none text-signal">$ </span>
              {deleteCommand}
            </p>
            <Input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              placeholder="Type the command to confirm"
              className="border-sidebar-border bg-sidebar font-mono text-sidebar-foreground placeholder:text-sidebar-foreground/40"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={confirmText !== deleteCommand || deleteMutation.isPending}
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
