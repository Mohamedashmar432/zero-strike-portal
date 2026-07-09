"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Cloud, GitBranch, Terminal } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { createScan, type CiProvider, type Scan, type ScanType } from "@/lib/api/scans";
import {
  newCicdScanSchema,
  newCloudScanSchema,
  newLocalScanSchema,
  type NewCicdScanInput,
  type NewCloudScanInput,
  type NewLocalScanInput,
} from "@/lib/validation/scan.schema";

const SCAN_TYPES: { value: ScanType; label: string; description: string; icon: typeof Terminal }[] = [
  { value: "local", label: "Local", description: "Run the ZeroStrike CLI scanner and upload results via an API key.", icon: Terminal },
  { value: "cloud", label: "Cloud", description: "Connect a repo via OAuth — coming soon. This saves your repo config only.", icon: Cloud },
  { value: "cicd", label: "CI/CD", description: "Wire into GitHub Actions, GitLab CI, or Azure Pipelines — coming soon.", icon: GitBranch },
];

const CI_PROVIDERS: { value: CiProvider; label: string }[] = [
  { value: "github_actions", label: "GitHub Actions" },
  { value: "gitlab_ci", label: "GitLab CI" },
  { value: "azure_pipelines", label: "Azure Pipelines" },
];

function TypeSelectStep({ onSelect }: { onSelect: (type: ScanType) => void }) {
  return (
    <>
      <DialogHeader>
        <DialogTitle>Set up a scan</DialogTitle>
        <DialogDescription>Choose how you want to scan this project.</DialogDescription>
      </DialogHeader>
      <div className="grid gap-3 sm:grid-cols-3">
        {SCAN_TYPES.map((t) => (
          <Button
            key={t.value}
            type="button"
            variant="outline"
            className="h-auto flex-col items-start gap-1 whitespace-normal p-3 text-left"
            onClick={() => onSelect(t.value)}
          >
            <t.icon className="size-5 text-muted-foreground" />
            <span className="font-medium">{t.label}</span>
            <span className="text-xs text-muted-foreground">{t.description}</span>
          </Button>
        ))}
      </div>
    </>
  );
}

function useCreateScan(projectId: string, onCreated: (scan: Scan) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { scan_type: ScanType; scan_label?: string; repo_url?: string; ci_provider?: CiProvider }) =>
      createScan(projectId, input),
    onSuccess: (scan) => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "scans"] });
      queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
      toast.success("Scan created");
      onCreated(scan);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to create scan"),
  });
}

function LocalConfigureStep({ projectId, onCreated }: { projectId: string; onCreated: (scan: Scan) => void }) {
  const { register, handleSubmit } = useForm<NewLocalScanInput>({ resolver: zodResolver(newLocalScanSchema) });
  const mutation = useCreateScan(projectId, onCreated);

  return (
    <form onSubmit={handleSubmit((values) => mutation.mutate({ scan_type: "local", ...values }))}>
      <DialogHeader>
        <DialogTitle>Local scan</DialogTitle>
        <DialogDescription>
          Run the CLI scanner on your machine and upload results using a project API key.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-2">
        <Label htmlFor="local-label">Label (optional)</Label>
        <Input id="local-label" placeholder="e.g. pre-release scan" autoComplete="off" {...register("scan_label")} />
      </div>
      <DialogFooter>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Creating…" : "Create scan"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function CloudConfigureStep({ projectId, onCreated }: { projectId: string; onCreated: (scan: Scan) => void }) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<NewCloudScanInput>({ resolver: zodResolver(newCloudScanSchema) });
  const mutation = useCreateScan(projectId, onCreated);

  return (
    <form onSubmit={handleSubmit((values) => mutation.mutate({ scan_type: "cloud", ...values }))}>
      <DialogHeader>
        <DialogTitle>Cloud scan</DialogTitle>
        <DialogDescription>
          Coming soon — this saves your repository config only, no OAuth connection is made yet.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="cloud-repo">Repository URL</Label>
          <Input id="cloud-repo" placeholder="https://github.com/org/repo" autoComplete="off" {...register("repo_url")} />
          {errors.repo_url && <p className="text-sm text-destructive">{errors.repo_url.message}</p>}
        </div>
        <div className="space-y-2">
          <Label htmlFor="cloud-label">Label (optional)</Label>
          <Input id="cloud-label" autoComplete="off" {...register("scan_label")} />
        </div>
      </div>
      <DialogFooter>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Save scan config"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function CicdConfigureStep({ projectId, onCreated }: { projectId: string; onCreated: (scan: Scan) => void }) {
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<NewCicdScanInput>({ resolver: zodResolver(newCicdScanSchema) });
  const mutation = useCreateScan(projectId, onCreated);
  const [ciProvider, setCiProvider] = useState<CiProvider>();

  return (
    <form onSubmit={handleSubmit((values) => mutation.mutate({ scan_type: "cicd", ...values }))}>
      <DialogHeader>
        <DialogTitle>CI/CD scan</DialogTitle>
        <DialogDescription>
          Coming soon — this saves your pipeline config only, no pipeline is wired up yet.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <div className="space-y-2">
          <Label>CI provider</Label>
          <div className="flex flex-wrap gap-1 rounded-lg border border-border p-0.5">
            {CI_PROVIDERS.map((p) => (
              <Button
                key={p.value}
                type="button"
                size="sm"
                variant={ciProvider === p.value ? "secondary" : "ghost"}
                onClick={() => {
                  setCiProvider(p.value);
                  setValue("ci_provider", p.value, { shouldValidate: true });
                }}
              >
                {p.label}
              </Button>
            ))}
          </div>
          {errors.ci_provider && <p className="text-sm text-destructive">{errors.ci_provider.message}</p>}
        </div>
        {ciProvider && (
          <code className="block min-w-0 rounded bg-muted px-2 py-1 text-xs break-all whitespace-pre-wrap">
            zerostrike scan . --project-id {projectId} --server $ZEROSTRIKE_SERVER --token $ZEROSTRIKE_TOKEN
          </code>
        )}
        <div className="space-y-2">
          <Label htmlFor="cicd-label">Label (optional)</Label>
          <Input id="cicd-label" autoComplete="off" {...register("scan_label")} />
        </div>
      </div>
      <DialogFooter>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Save scan config"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function CreatedStep({ scan, onDismiss }: { scan: Scan; onDismiss: () => void }) {
  const router = useRouter();

  return (
    <>
      <DialogHeader>
        <DialogTitle>Scan created</DialogTitle>
        <DialogDescription>
          {scan.scan_type === "local"
            ? "Next: make sure this project has an active API key so the CLI can authenticate."
            : "Saved. Real execution for this scan type ships in a later sprint."}
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button variant="ghost" onClick={onDismiss}>
          Done
        </Button>
        {scan.scan_type === "local" && (
          <Button
            onClick={() => {
              router.push(`/projects/${scan.project_id}?tab=keys`);
              onDismiss();
            }}
          >
            Set up API key
          </Button>
        )}
      </DialogFooter>
    </>
  );
}

export function NewScanDialog({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [scanType, setScanType] = useState<ScanType | null>(null);
  const [createdScan, setCreatedScan] = useState<Scan | null>(null);

  function close() {
    setOpen(false);
    setScanType(null);
    setCreatedScan(null);
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
      <DialogTrigger render={<Button>New scan</Button>} />
      <DialogContent>
        {createdScan ? (
          <CreatedStep scan={createdScan} onDismiss={close} />
        ) : scanType === "local" ? (
          <LocalConfigureStep projectId={projectId} onCreated={setCreatedScan} />
        ) : scanType === "cloud" ? (
          <CloudConfigureStep projectId={projectId} onCreated={setCreatedScan} />
        ) : scanType === "cicd" ? (
          <CicdConfigureStep projectId={projectId} onCreated={setCreatedScan} />
        ) : (
          <TypeSelectStep onSelect={setScanType} />
        )}
      </DialogContent>
    </Dialog>
  );
}
