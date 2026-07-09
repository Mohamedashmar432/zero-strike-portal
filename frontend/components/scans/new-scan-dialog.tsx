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
import { createApiKey } from "@/lib/api/api-keys";
import { ApiError } from "@/lib/api/client";
import { createCloudScan, type CiProvider, type ScanType } from "@/lib/api/scans";
import { newCloudScanSchema, type NewCloudScanInput } from "@/lib/validation/scan.schema";

function portalOrigin(): string {
  const env = process.env.NEXT_PUBLIC_PORTAL_ORIGIN;
  if (env) return env.replace(/\/$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return "https://your-portal";
}

const SCAN_TYPES: { value: ScanType; label: string; description: string; icon: typeof Terminal }[] = [
  { value: "local", label: "Local", description: "Run the ZeroStrike CLI on your machine and upload results with an API key.", icon: Terminal },
  { value: "cloud", label: "Cloud", description: "Give ZeroStrike a repo URL and it clones + scans it server-side.", icon: Cloud },
  { value: "cicd", label: "CI/CD", description: "Add ZeroStrike to your pipeline (GitHub Actions, GitLab CI, Azure Pipelines).", icon: GitBranch },
];

const CI_PROVIDERS: { value: CiProvider; label: string }[] = [
  { value: "github_actions", label: "GitHub Actions" },
  { value: "gitlab_ci", label: "GitLab CI" },
  { value: "azure_pipelines", label: "Azure Pipelines" },
];

function CopyBlock({ text, label }: { text: string; label?: string }) {
  return (
    <div className="space-y-1">
      {label && <Label>{label}</Label>}
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 rounded bg-muted px-2 py-1.5 text-xs break-all whitespace-pre-wrap">
          {text}
        </code>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            navigator.clipboard.writeText(text);
            toast.success("Copied");
          }}
        >
          Copy
        </Button>
      </div>
    </div>
  );
}

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

function LocalSetupStep({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [rawToken, setRawToken] = useState<string | null>(null);
  const generate = useMutation({
    mutationFn: () => createApiKey(projectId, { label: "local CLI scan", expires_in_days: 90 }),
    onSuccess: (key) => setRawToken(key.raw_token),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to create API key"),
  });

  const token = rawToken ?? "<API_KEY>";
  const command = `zerostrike scan . --server ${portalOrigin()} --project-id ${projectId} --token ${token}`;

  return (
    <>
      <DialogHeader>
        <DialogTitle>Local scan</DialogTitle>
        <DialogDescription>
          Run the ZeroStrike CLI on your machine — it uploads results here automatically. A scan appears
          in this list once the CLI runs.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        {rawToken ? (
          <div className="space-y-1">
            <p className="text-sm font-medium text-amber-500">
              Copy this API key now — it won&apos;t be shown again.
            </p>
            <CopyBlock text={rawToken} />
          </div>
        ) : (
          <Button type="button" onClick={() => generate.mutate()} disabled={generate.isPending}>
            {generate.isPending ? "Generating…" : "Generate an API key"}
          </Button>
        )}
        <CopyBlock label="Then run" text={command} />
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          Done
        </Button>
      </DialogFooter>
    </>
  );
}

function cicdSnippet(provider: CiProvider, origin: string, projectId: string): string {
  const cmdGh = `zerostrike scan . --server ${origin} --project-id ${projectId} --token \${{ secrets.ZEROSTRIKE_TOKEN }}`;
  const cmdSh = `zerostrike scan . --server ${origin} --project-id ${projectId} --token $ZEROSTRIKE_TOKEN`;
  const cmdAz = `zerostrike scan . --server ${origin} --project-id ${projectId} --token $(ZEROSTRIKE_TOKEN)`;
  if (provider === "github_actions") {
    return [
      "# .github/workflows/zerostrike.yml",
      "name: ZeroStrike SAST",
      "on: [push, pull_request]",
      "jobs:",
      "  zerostrike:",
      "    runs-on: ubuntu-latest",
      "    steps:",
      "      - uses: actions/checkout@v4",
      "      - name: ZeroStrike scan",
      `        run: ${cmdGh}`,
    ].join("\n");
  }
  if (provider === "gitlab_ci") {
    return [
      "# .gitlab-ci.yml",
      "zerostrike_scan:",
      "  stage: test",
      "  script:",
      `    - ${cmdSh}`,
    ].join("\n");
  }
  return [
    "# azure-pipelines.yml",
    "steps:",
    `  - script: ${cmdAz}`,
    "    displayName: ZeroStrike scan",
  ].join("\n");
}

function CicdSetupStep({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [provider, setProvider] = useState<CiProvider>();

  return (
    <>
      <DialogHeader>
        <DialogTitle>CI/CD scan</DialogTitle>
        <DialogDescription>
          Add ZeroStrike to your pipeline. Store an API key as a secret named{" "}
          <code>ZEROSTRIKE_TOKEN</code> (generate one on the API Keys tab), then drop in the snippet.
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
                variant={provider === p.value ? "secondary" : "ghost"}
                onClick={() => setProvider(p.value)}
              >
                {p.label}
              </Button>
            ))}
          </div>
        </div>
        {provider && <CopyBlock label="Pipeline snippet" text={cicdSnippet(provider, portalOrigin(), projectId)} />}
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          Done
        </Button>
      </DialogFooter>
    </>
  );
}

function CloudCreateStep({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<NewCloudScanInput>({ resolver: zodResolver(newCloudScanSchema) });

  const mutation = useMutation({
    mutationFn: (values: NewCloudScanInput) => createCloudScan(projectId, values),
    onSuccess: (scan) => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "scans"] });
      queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
      toast.success("Cloud scan started");
      onClose();
      router.push(`/projects/${projectId}/scans/${scan.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to start cloud scan"),
  });

  return (
    <form onSubmit={handleSubmit((values) => mutation.mutate(values))}>
      <DialogHeader>
        <DialogTitle>Cloud scan</DialogTitle>
        <DialogDescription>
          ZeroStrike clones the repository and scans it on the server. Provide a token below for private
          repos — it is used only for this clone and never stored.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="cloud-repo">Repository URL</Label>
          <Input id="cloud-repo" placeholder="https://github.com/org/repo" autoComplete="off" {...register("repo_url")} />
          {errors.repo_url && <p className="text-sm text-destructive">{errors.repo_url.message}</p>}
        </div>
        <div className="space-y-2">
          <Label htmlFor="cloud-branch">Branch (optional)</Label>
          <Input id="cloud-branch" placeholder="main" autoComplete="off" {...register("branch")} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="cloud-token">Access token (private repos only)</Label>
          <Input id="cloud-token" type="password" autoComplete="off" {...register("repo_token")} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="cloud-label">Label (optional)</Label>
          <Input id="cloud-label" autoComplete="off" {...register("scan_label")} />
        </div>
      </div>
      <DialogFooter>
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Starting…" : "Start cloud scan"}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function NewScanDialog({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [scanType, setScanType] = useState<ScanType | null>(null);

  function close() {
    setOpen(false);
    setScanType(null);
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
      <DialogTrigger render={<Button>New scan</Button>} />
      <DialogContent>
        {scanType === "local" ? (
          <LocalSetupStep projectId={projectId} onDone={close} />
        ) : scanType === "cloud" ? (
          <CloudCreateStep projectId={projectId} onClose={close} />
        ) : scanType === "cicd" ? (
          <CicdSetupStep projectId={projectId} onDone={close} />
        ) : (
          <TypeSelectStep onSelect={setScanType} />
        )}
      </DialogContent>
    </Dialog>
  );
}
