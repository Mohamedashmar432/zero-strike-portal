"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { PageHeader } from "@/components/layout/page-header";
import { RepoConnectWizard } from "@/components/repos/repo-connect-wizard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { createProject, type Project } from "@/lib/api/projects";
import { createProjectSchema, type CreateProjectInput } from "@/lib/validation/project.schema";

export default function NewProjectPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [created, setCreated] = useState<Project | null>(null);

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
      setCreated(project);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to create project"),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="New project"
        description="A project groups the SAST scans, members, and scanner project tokens for one codebase."
        breadcrumb={<Breadcrumbs items={[{ label: "Projects", href: "/projects" }, { label: "New project" }]} />}
      />

      {!created ? (
        <Card className="mx-auto max-w-xl">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">Step 1 of 2 — Project details</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit((values) => mutation.mutate(values))} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" autoComplete="off" {...register("name")} />
                {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Input id="description" autoComplete="off" {...register("description")} />
              </div>
              <div className="flex items-center justify-between border-t border-border pt-4">
                <Button variant="ghost" nativeButton={false} render={<Link href="/projects" />}>
                  Cancel
                </Button>
                <Button type="submit" disabled={mutation.isPending}>
                  {mutation.isPending ? "Creating…" : "Create project"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      ) : (
        <div className="mx-auto max-w-xl space-y-4">
          <Card className="border-status-success/40 bg-status-success/5">
            <CardContent className="py-4 text-sm text-foreground">
              <span className="font-medium">&quot;{created.name}&quot;</span> is ready. Connect a repository now so
              cloud scans can reuse it, or skip and set this up later.
            </CardContent>
          </Card>
          <RepoConnectWizard
            projectId={created.id}
            cancelHref={`/projects/${created.id}`}
            cancelLabel="Skip for now"
            onConnected={() => router.push(`/projects/${created.id}?tab=repos`)}
          />
        </div>
      )}
    </div>
  );
}
