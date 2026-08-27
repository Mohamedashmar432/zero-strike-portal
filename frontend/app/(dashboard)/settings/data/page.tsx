"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Database, RotateCcw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { EmptyState } from "@/components/common/empty-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { getDataStats, purgeData, reapStuckScans } from "@/lib/api/admin-data";
import { ApiError } from "@/lib/api/client";
import { listProjects } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import { useHasRole } from "@/lib/hooks/use-has-role";

const ALL_PROJECTS = "__all__";
const CONFIRM_PHRASE = "DELETE";

export default function DataSettingsPage() {
  const isAdmin = useHasRole("admin");
  const queryClient = useQueryClient();

  const [scope, setScope] = useState<string>(ALL_PROJECTS);
  const projectId = scope === ALL_PROJECTS ? undefined : scope;
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmText, setConfirmText] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data: projects } = useQuery({
    queryKey: queryKeys.projects.all(),
    queryFn: () => listProjects(1, 100),
    enabled: isAdmin,
  });

  const {
    data: stats,
    isPending,
    isFetching,
  } = useQuery({
    queryKey: queryKeys.admin.dataStats(projectId),
    queryFn: () => getDataStats(projectId),
    enabled: isAdmin,
  });

  const purge = useMutation({
    mutationFn: () => purgeData(selected, projectId),
    onSuccess: (result) => {
      toast.success(
        result.total_deleted === 0
          ? "Nothing to delete — already clear"
          : `Deleted ${result.total_deleted} record${result.total_deleted === 1 ? "" : "s"}`
      );
      setDialogOpen(false);
      setConfirmText("");
      setSelected([]);
      // Purged data feeds most of the portal, so drop the whole cache rather than
      // enumerating every dependent key.
      queryClient.invalidateQueries();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Purge failed"),
  });

  const reap = useMutation({
    mutationFn: reapStuckScans,
    onSuccess: () => {
      toast.success("Stuck scans reclaimed");
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.dataStats(projectId) });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to reap scans"),
  });

  if (!isAdmin) {
    return (
      <div className="max-w-2xl space-y-6">
        <Header />
        <EmptyState
          icon={Database}
          title="Admins only"
          description="Only portal admins can view or delete portal data."
        />
      </div>
    );
  }

  const categories = stats?.categories ?? [];
  const byKey = Object.fromEntries(categories.map((c) => [c.key, c]));
  // A category's `implies` are deleted too — show the admin the real blast radius, not
  // just what they ticked.
  const effective = new Set<string>();
  const walk = (key: string) => {
    if (effective.has(key)) return;
    effective.add(key);
    byKey[key]?.implies.forEach(walk);
  };
  selected.forEach(walk);

  const affected = categories.filter((c) => effective.has(c.key));
  const totalAffected = affected.reduce((sum, c) => sum + c.total, 0);
  const scopeLabel =
    projectId === undefined
      ? "the entire portal"
      : (projects?.items.find((p) => p.id === projectId)?.name ?? "this project");

  const toggle = (key: string) =>
    setSelected((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  // One-click "clear the test data": portal-wide scope + the projects category, which
  // implies every project-scoped category. Same dialog, same typed confirmation.
  const resetPortal = () => {
    setScope(ALL_PROJECTS);
    setSelected(["projects"]);
    setDialogOpen(true);
  };

  return (
    <div className="max-w-3xl space-y-6">
      <Header />

      <Alert>
        <ShieldCheck />
        <AlertTitle>What is never deleted</AlertTitle>
        <AlertDescription>
          User accounts, workspace settings, AI provider keys, repository credentials and published
          scanner binaries are always kept. Only scan output and project records are removable here.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">Scope</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Label htmlFor="scope">Delete data from</Label>
          <Select
            value={scope}
            onValueChange={(v) => {
              // base-ui emits null when the select is cleared; fall back to the
              // "all projects" sentinel rather than an empty scope.
              setScope(v ?? ALL_PROJECTS);
              setSelected([]);
            }}
          >
            <SelectTrigger id="scope" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_PROJECTS}>All projects (portal-wide)</SelectItem>
              {projects?.items.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Counts below reflect the selected scope.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">
            What to delete
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {isPending ? (
            <Skeleton className="h-56 w-full" />
          ) : (
            categories.map((category) => {
              const checked = selected.includes(category.key);
              const pulledIn = !checked && effective.has(category.key);
              return (
                <label
                  key={category.key}
                  htmlFor={`cat-${category.key}`}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-accent/40 ${
                    checked || pulledIn ? "border-destructive/40 bg-destructive/5" : ""
                  }`}
                >
                  <input
                    id={`cat-${category.key}`}
                    type="checkbox"
                    checked={checked || pulledIn}
                    disabled={pulledIn}
                    onChange={() => toggle(category.key)}
                    className="mt-1 size-4 accent-red-600"
                  />
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{category.label}</span>
                      <Badge variant="secondary">{category.total.toLocaleString()}</Badge>
                      {category.destructive && <Badge variant="destructive">Irreversible</Badge>}
                      {pulledIn && <Badge variant="outline">Included automatically</Badge>}
                    </div>
                    <p className="text-xs text-muted-foreground">{category.description}</p>
                    <p className="font-mono text-[11px] text-muted-foreground/70">
                      {category.collections
                        .map((c) => `${c.name} (${c.count.toLocaleString()})`)
                        .join(" · ")}
                    </p>
                  </div>
                </label>
              );
            })
          )}
        </CardContent>
      </Card>

      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-destructive">
            <AlertTriangle className="size-4" /> Danger Zone
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p className="text-sm text-muted-foreground">
              {selected.length === 0
                ? "Select at least one category above."
                : `Deletes ${totalAffected.toLocaleString()} record${
                    totalAffected === 1 ? "" : "s"
                  } from ${scopeLabel}. This cannot be undone.`}
            </p>
            <Button
              variant="destructive"
              disabled={selected.length === 0}
              onClick={() => setDialogOpen(true)}
            >
              Delete Data
            </Button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4 border-t pt-4">
            <p className="text-sm text-muted-foreground">
              Wipe every project in the portal and everything under it — the one-click reset for
              clearing test data. User accounts and settings are kept.
            </p>
            <Button variant="destructive" onClick={resetPortal}>
              Delete all projects
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-normal text-muted-foreground">
            <RotateCcw className="size-4" /> Stuck scans
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">
            Run the queue reaper now instead of waiting for the timeout window. Scans wedged in
            <span className="font-mono"> running </span>
            are failed and their concurrency slot released.
          </p>
          <Button variant="outline" onClick={() => reap.mutate()} disabled={reap.isPending}>
            {reap.isPending ? "Reaping…" : "Reap stuck scans"}
          </Button>
        </CardContent>
      </Card>

      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) setConfirmText("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete portal data</DialogTitle>
            <DialogDescription>
              This permanently deletes {totalAffected.toLocaleString()} record
              {totalAffected === 1 ? "" : "s"} from <strong>{scopeLabel}</strong>. There is no undo.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <ul className="space-y-1 text-sm">
              {affected.map((c) => (
                <li key={c.key} className="flex items-center justify-between gap-4">
                  <span>{c.label}</span>
                  <span className="font-mono text-muted-foreground">
                    {c.total.toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
            <div className="space-y-2">
              <Label htmlFor="confirm">
                Type <span className="font-mono font-semibold">{CONFIRM_PHRASE}</span> to confirm
              </Label>
              <Input
                id="confirm"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder={CONFIRM_PHRASE}
                className="font-mono"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              // isFetching: switching scope refetches the counts, and confirming an
              // irreversible wipe against a stale/zero total is worse than a short wait.
              disabled={confirmText !== CONFIRM_PHRASE || purge.isPending || isFetching}
              onClick={() => purge.mutate()}
            >
              {purge.isPending ? "Deleting…" : isFetching ? "Counting…" : "Delete Data"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Header() {
  return (
    <div>
      <h2 className="text-lg font-semibold">Data Management</h2>
      <p className="text-sm text-muted-foreground">
        Inspect what the portal is storing and clear out test or demo data.
      </p>
    </div>
  );
}
