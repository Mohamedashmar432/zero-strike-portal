"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import {
  deleteCustomRule,
  fpRateLabel,
  getCustomRules,
  getPending,
  getRuleHistory,
  getRules,
  getVersions,
  hasPendingChanges,
  publishVersion,
  restoreRule,
  retireRule,
  rollBackVersion,
  saveCustomRule,
  setThresholds,
  type RuleRow,
} from "@/lib/api/scan-engine";
import { queryKeys } from "@/lib/api/query-keys";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);
const formatDate = (value: string | null) => (value ? new Date(value).toLocaleString() : "—");

/** Refetch everything on the page after any change, since rules, pending and versions all move together. */
function useRefresh() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: queryKeys.admin.scanEngine() });
}

function RuleHistoryDialog({ rule, onClose }: { rule: RuleRow | null; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: [...queryKeys.admin.scanEngine(), "history", rule?.rule_id],
    queryFn: () => getRuleHistory(rule!.rule_id),
    enabled: !!rule,
  });
  return (
    <Dialog open={!!rule} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{rule?.rule_id} false-positive tags</DialogTitle>
          <DialogDescription>
            Who tagged what, and why. Counts and comments only; no client code is shown here.
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : !data || data.fp_tags.length === 0 ? (
          <p className="text-sm text-muted-foreground">No false-positive tags for this rule.</p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Project</TableHead>
                  <TableHead>Date</TableHead>
                  <TableHead>By</TableHead>
                  <TableHead>Comment</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.fp_tags.map((t, i) => (
                  <TableRow key={i}>
                    <TableCell>{t.project_name}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDate(t.tagged_at)}</TableCell>
                    <TableCell>{t.tagged_by ?? "—"}</TableCell>
                    <TableCell className="max-w-64 whitespace-normal">{t.comment ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ReasonDialog({
  open,
  title,
  description,
  confirmLabel,
  fieldLabel,
  required,
  pending,
  onClose,
  onSubmit,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  fieldLabel: string;
  required: boolean;
  pending: boolean;
  onClose: () => void;
  onSubmit: (text: string) => void;
}) {
  const [text, setText] = useState("");
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setText("");
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="reason-text">{fieldLabel}</Label>
          <Textarea id="reason-text" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={pending || (required && text.trim() === "")}
            onClick={() => {
              onSubmit(text.trim());
              setText("");
            }}
          >
            {pending ? "Saving…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ThresholdsForm({ tags, percent }: { tags: number; percent: number }) {
  const refresh = useRefresh();
  const [minTags, setMinTags] = useState(String(tags));
  const [minPercent, setMinPercent] = useState(String(percent));
  const save = useMutation({
    mutationFn: () => setThresholds(Number(minTags), Number(minPercent)),
    onSuccess: () => {
      toast.success("Noisy thresholds saved");
      refresh();
    },
    onError: (err) => toast.error(errorText(err, "Could not save thresholds")),
  });
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="space-y-1">
        <Label htmlFor="noisy-tags">Noisy at (FP tags)</Label>
        <Input id="noisy-tags" type="number" min={1} className="w-28" value={minTags} onChange={(e) => setMinTags(e.target.value)} />
      </div>
      <div className="space-y-1">
        <Label htmlFor="noisy-percent">and FP rate (%)</Label>
        <Input id="noisy-percent" type="number" min={1} max={100} className="w-28" value={minPercent} onChange={(e) => setMinPercent(e.target.value)} />
      </div>
      <Button variant="outline" size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
        Save thresholds
      </Button>
    </div>
  );
}

function RulesTab() {
  const refresh = useRefresh();
  const { data, isLoading, isError } = useQuery({ queryKey: [...queryKeys.admin.scanEngine(), "rules"], queryFn: getRules });
  const [historyRule, setHistoryRule] = useState<RuleRow | null>(null);
  const [retiring, setRetiring] = useState<RuleRow | null>(null);

  const retire = useMutation({
    mutationFn: ({ ruleId, reason }: { ruleId: string; reason: string }) => retireRule(ruleId, reason),
    onSuccess: () => {
      toast.success("Rule retired in the draft. Publish a version to apply it.");
      setRetiring(null);
      refresh();
    },
    onError: (err) => toast.error(errorText(err, "Could not retire the rule")),
  });
  const restore = useMutation({
    mutationFn: (ruleId: string) => restoreRule(ruleId),
    onSuccess: () => {
      toast.success("Rule restored in the draft. Publish a version to apply it.");
      refresh();
    },
    onError: (err) => toast.error(errorText(err, "Could not restore the rule")),
  });

  return (
    <div className="space-y-4">
      {data && <ThresholdsForm key={`${data.noisy_min_fp_tags}-${data.noisy_min_fp_percent}`} tags={data.noisy_min_fp_tags} percent={data.noisy_min_fp_percent} />}
      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        isEmpty={!!data && data.rules.length === 0}
        emptyState={<EmptyState title="No rule has produced a finding yet." />}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Rule</TableHead>
              <TableHead>Severity</TableHead>
              <TableHead>Language</TableHead>
              <TableHead className="text-right">Findings</TableHead>
              <TableHead className="text-right">FP tags</TableHead>
              <TableHead className="text-right">FP rate</TableHead>
              <TableHead className="text-right">Projects</TableHead>
              <TableHead>State</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.rules.map((r) => (
              <TableRow key={r.rule_id}>
                <TableCell>
                  <div className="font-mono text-xs">{r.rule_id}</div>
                  <div className="text-xs text-muted-foreground">{r.title ?? "—"}</div>
                </TableCell>
                <TableCell>{r.severity ?? "—"}</TableCell>
                <TableCell>{r.language ?? "—"}</TableCell>
                <TableCell className="text-right">{r.total_findings}</TableCell>
                <TableCell className="text-right">{r.fp_tags}</TableCell>
                <TableCell className="text-right">{fpRateLabel(r.fp_rate)}</TableCell>
                <TableCell className="text-right">{r.projects_affected}</TableCell>
                <TableCell className="space-x-1">
                  <Badge variant={r.state === "retired" ? "secondary" : "outline"}>{r.state}</Badge>
                  {r.noisy && <Badge variant="destructive">Noisy</Badge>}
                  {r.pending && <Badge variant="outline">draft</Badge>}
                </TableCell>
                <TableCell className="space-x-2 text-right whitespace-nowrap">
                  {r.fp_tags > 0 && (
                    <Button variant="ghost" size="sm" onClick={() => setHistoryRule(r)}>
                      Tags
                    </Button>
                  )}
                  {r.state === "retired" ? (
                    <Button variant="outline" size="sm" disabled={restore.isPending} onClick={() => restore.mutate(r.rule_id)}>
                      Restore
                    </Button>
                  ) : r.state === "active" ? (
                    <Button variant="outline" size="sm" onClick={() => setRetiring(r)}>
                      Retire
                    </Button>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
      <RuleHistoryDialog rule={historyRule} onClose={() => setHistoryRule(null)} />
      <ReasonDialog
        open={!!retiring}
        title={`Retire ${retiring?.rule_id ?? "rule"}`}
        description="Findings from a retired rule are hidden from counts, reports and blocking for every project once a version is published."
        confirmLabel="Retire in draft"
        fieldLabel="Reason (required)"
        required
        pending={retire.isPending}
        onClose={() => setRetiring(null)}
        onSubmit={(reason) => retiring && retire.mutate({ ruleId: retiring.rule_id, reason })}
      />
    </div>
  );
}

const YAML_TEMPLATE = `id: ZS-CUSTOM-001
name: Example custom rule
version: "1.0.0"
language: python
category: dangerous-functions
severity: high
confidence: high
lifecycle: released
description: |
  What the rule looks for.
message: "Explain the finding"
match:
  kind: call
  callee: custom_danger
fix_suggestion: "How to fix it."
rationale: |
  Why it matters.
`;

function CustomRulesTab() {
  const refresh = useRefresh();
  const { data, isLoading, isError } = useQuery({ queryKey: [...queryKeys.admin.scanEngine(), "custom"], queryFn: getCustomRules });
  const [yaml, setYaml] = useState(YAML_TEMPLATE);
  const [vulnerable, setVulnerable] = useState("");
  const [safe, setSafe] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => saveCustomRule({ yaml, vulnerable_sample: vulnerable, safe_sample: safe }),
    onSuccess: () => {
      toast.success("Rule validated and saved to the draft. Publish a version to apply it.");
      refresh();
    },
    // The 422 detail says which check failed (scanner validator, vulnerable sample, safe sample).
    onError: (err) => toast.error(errorText(err, "Could not save the rule")),
  });
  const remove = useMutation({
    mutationFn: (ruleId: string) => deleteCustomRule(ruleId),
    onSuccess: () => {
      toast.success("Custom rule removed from the draft");
      setDeleting(null);
      refresh();
    },
    onError: (err) => toast.error(errorText(err, "Could not delete the rule")),
  });

  return (
    <div className="space-y-4">
      <div className="space-y-3 rounded-lg border border-border/70 p-4">
        <p className="text-sm text-muted-foreground">
          Paste a rule in the scanner&apos;s YAML format (id must start with ZS-CUSTOM-). Saving runs the scanner on both
          samples: the rule must fire on the vulnerable one and stay silent on the safe one.
        </p>
        <div className="space-y-1.5">
          <Label htmlFor="rule-yaml">Rule YAML</Label>
          <Textarea id="rule-yaml" className="min-h-48 font-mono text-xs" value={yaml} onChange={(e) => setYaml(e.target.value)} />
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="rule-vulnerable">Vulnerable sample</Label>
            <Textarea id="rule-vulnerable" className="min-h-28 font-mono text-xs" value={vulnerable} onChange={(e) => setVulnerable(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-safe">Safe sample</Label>
            <Textarea id="rule-safe" className="min-h-28 font-mono text-xs" value={safe} onChange={(e) => setSafe(e.target.value)} />
          </div>
        </div>
        <Button disabled={save.isPending || !yaml.trim() || !vulnerable.trim() || !safe.trim()} onClick={() => save.mutate()}>
          {save.isPending ? "Validating…" : "Validate and save"}
        </Button>
      </div>

      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        isEmpty={!!data && data.length === 0}
        emptyState={<EmptyState title="No custom rules yet." />}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Rule</TableHead>
              <TableHead>Language</TableHead>
              <TableHead>Last validated</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((c) => (
              <TableRow key={c.rule_id}>
                <TableCell className="font-mono text-xs">{c.rule_id}</TableCell>
                <TableCell>{c.language}</TableCell>
                <TableCell>{formatDate(c.last_validated_at)}</TableCell>
                <TableCell className="space-x-2 text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setYaml(c.yaml);
                      setVulnerable(c.vulnerable_sample);
                      setSafe(c.safe_sample);
                    }}
                  >
                    Edit
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setDeleting(c.rule_id)}>
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete custom rule"
        description={`${deleting ?? "This rule"} is removed from the draft. Scans keep using it until you publish a version without it.`}
        confirmLabel="Delete"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  );
}

function VersionsTab() {
  const refresh = useRefresh();
  const pendingQuery = useQuery({ queryKey: [...queryKeys.admin.scanEngine(), "pending"], queryFn: getPending });
  const versions = useQuery({ queryKey: [...queryKeys.admin.scanEngine(), "versions"], queryFn: getVersions });
  const [publishing, setPublishing] = useState(false);
  const [rollingBack, setRollingBack] = useState<number | null>(null);

  const publish = useMutation({
    mutationFn: (changelog: string) => publishVersion(changelog),
    onSuccess: () => {
      toast.success("Rule pack published. The next scan uses it.");
      setPublishing(false);
      refresh();
    },
    onError: (err) => toast.error(errorText(err, "Could not publish")),
  });
  const rollBack = useMutation({
    mutationFn: (version: number) => rollBackVersion(version),
    onSuccess: () => {
      toast.success("Rolled back. The old contents were published as a new version.");
      setRollingBack(null);
      refresh();
    },
    onError: (err) => toast.error(errorText(err, "Could not roll back")),
  });

  const pending = pendingQuery.data;
  const changed = hasPendingChanges(pending);
  const lines = pending
    ? [
        ["Retire", pending.retired],
        ["Restore", pending.restored],
        ["Add custom rule", pending.custom_added],
        ["Edit custom rule", pending.custom_edited],
        ["Remove custom rule", pending.custom_removed],
      ].filter(([, ids]) => (ids as string[]).length > 0)
    : [];

  return (
    <div className="space-y-4">
      <Alert>
        <AlertTitle>{changed ? "Draft has unpublished changes" : "No pending changes"}</AlertTitle>
        <AlertDescription>
          {changed ? (
            <ul className="mt-1 list-disc pl-5">
              {lines.map(([label, ids]) => (
                <li key={label as string}>
                  {label as string}: <span className="font-mono">{(ids as string[]).join(", ")}</span>
                </li>
              ))}
            </ul>
          ) : (
            "Retire a rule or add a custom rule, then publish to make it a new version."
          )}
          <Button className="mt-3" size="sm" disabled={!changed} onClick={() => setPublishing(true)}>
            Publish new version
          </Button>
        </AlertDescription>
      </Alert>

      <DataTableCard
        isLoading={versions.isLoading}
        isError={versions.isError}
        isEmpty={!!versions.data && versions.data.length === 0}
        emptyState={<EmptyState title="Nothing published yet. Scans run on the scanner's built-in rules." />}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Version</TableHead>
              <TableHead>Changelog</TableHead>
              <TableHead className="text-right">Retired</TableHead>
              <TableHead className="text-right">Custom</TableHead>
              <TableHead>Published</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {versions.data?.map((v, i) => (
              <TableRow key={v.version}>
                <TableCell className="font-mono text-xs">
                  v{v.version} {i === 0 && <Badge variant="outline">active</Badge>}
                </TableCell>
                <TableCell className="max-w-80 whitespace-normal">
                  {v.changelog}
                  {v.rolled_back_from != null && (
                    <span className="text-muted-foreground"> (rollback to v{v.rolled_back_from})</span>
                  )}
                </TableCell>
                <TableCell className="text-right">{v.retired_count}</TableCell>
                <TableCell className="text-right">{v.custom_count}</TableCell>
                <TableCell className="whitespace-nowrap">{formatDate(v.published_at)}</TableCell>
                <TableCell className="text-right">
                  {i > 0 && (
                    <Button variant="outline" size="sm" onClick={() => setRollingBack(v.version)}>
                      Roll back
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>

      <ReasonDialog
        open={publishing}
        title="Publish new rule pack version"
        description="Freezes the draft as the next version. It takes effect on the next scan, and is recorded in the audit log."
        confirmLabel="Publish"
        fieldLabel="Changelog (required)"
        required
        pending={publish.isPending}
        onClose={() => setPublishing(false)}
        onSubmit={(text) => publish.mutate(text)}
      />
      <ConfirmDialog
        open={rollingBack !== null}
        onOpenChange={(o) => !o && setRollingBack(null)}
        title={`Roll back to v${rollingBack ?? ""}`}
        description="Publishes that version's contents as a new version and discards the current draft. History is not rewritten."
        confirmLabel="Roll back"
        destructive={false}
        pending={rollBack.isPending}
        onConfirm={() => rollingBack !== null && rollBack.mutate(rollingBack)}
      />
    </div>
  );
}

export default function ScanEnginePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Scan Engine"
        description="Which scanner rules are noisy, retire a rule, add a custom rule, and publish the result as a versioned rule pack."
      />
      <Tabs defaultValue="rules">
        <TabsList variant="line">
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="custom">Custom rules</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
        </TabsList>
        <TabsContent value="rules" className="pt-4">
          <RulesTab />
        </TabsContent>
        <TabsContent value="custom" className="pt-4">
          <CustomRulesTab />
        </TabsContent>
        <TabsContent value="versions" className="pt-4">
          <VersionsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
