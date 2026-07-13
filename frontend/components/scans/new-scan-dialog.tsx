"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { createApiKey } from "@/lib/api/api-keys";
import { ApiError } from "@/lib/api/client";
import { listProjectRepos, type ProjectRepo } from "@/lib/api/project-repos";
import { createCloudScan, type CiProvider, type ScanType } from "@/lib/api/scans";
import { newCloudScanSchema, type NewCloudScanInput } from "@/lib/validation/scan.schema";

function portalOrigin(): string {
  const env = process.env.NEXT_PUBLIC_PORTAL_ORIGIN;
  if (env) return env.replace(/\/$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return "https://your-portal";
}

const SCAN_TYPES: { value: ScanType; label: string; description: string; icon: typeof Terminal }[] = [
  { value: "local", label: "Local", description: "Run the ZeroStrike CLI on your machine and upload results with a project token.", icon: Terminal },
  { value: "cloud", label: "Cloud", description: "Give ZeroStrike a repo URL and it clones + scans it server-side.", icon: Cloud },
  { value: "cicd", label: "CI/CD", description: "Add ZeroStrike to your pipeline (GitHub Actions, GitLab CI, Azure Pipelines).", icon: GitBranch },
];

const CI_PROVIDERS: { value: CiProvider; label: string }[] = [
  { value: "github_actions", label: "GitHub Actions" },
  { value: "gitlab_ci", label: "GitLab CI" },
  { value: "azure_pipelines", label: "Azure Pipelines" },
];

function downloadTextFile(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function CopyBlock({ text, label, filename }: { text: string; label?: string; filename?: string }) {
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
        {filename && (
          <Button type="button" size="sm" variant="outline" onClick={() => downloadTextFile(filename, text)}>
            Download
          </Button>
        )}
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
            className="h-auto flex-col items-start gap-2 whitespace-normal p-4 text-left transition-colors hover:border-primary/50 hover:bg-accent"
            onClick={() => onSelect(t.value)}
          >
            <t.icon className="size-5 text-brand" />
            <span className="font-medium text-foreground">{t.label}</span>
            <span className="text-xs text-muted-foreground">{t.description}</span>
          </Button>
        ))}
      </div>
    </>
  );
}

type LocalOs = "linux" | "macos" | "windows";

const LOCAL_OS: { value: LocalOs; label: string }[] = [
  { value: "linux", label: "Linux" },
  { value: "macos", label: "macOS" },
  { value: "windows", label: "Windows" },
];

function defaultLocalOs(): LocalOs {
  if (typeof navigator === "undefined") return "linux";
  if (/Win/i.test(navigator.userAgent)) return "windows";
  if (/Mac/i.test(navigator.userAgent)) return "macos";
  return "linux";
}

// Hardcoded to "latest" for now (YAGNI) — add a `version` param + version-picker UI if pinning
// a specific zerostrike release ever becomes necessary.
function localInstallCmd(os: LocalOs, origin: string): string {
  if (os === "windows") {
    return `Invoke-WebRequest ${origin}/api/v1/downloads/zerostrike/latest/windows-amd64 -OutFile zerostrike.exe`;
  }
  if (os === "macos") {
    return `curl -fsSL ${origin}/api/v1/downloads/zerostrike/latest/darwin-arm64 -o zerostrike && chmod +x zerostrike`;
  }
  return `curl -fsSL ${origin}/api/v1/downloads/zerostrike/latest/linux-amd64 -o zerostrike && chmod +x zerostrike`;
}

function localRunCmd(os: LocalOs, token: string): string {
  const bin = os === "windows" ? ".\\zerostrike.exe" : "./zerostrike";
  return `${bin} scan . --server ${portalOrigin()} --token ${token}`;
}

function localFilename(os: LocalOs): string {
  return os === "windows" ? "zerostrike-scan.ps1" : "zerostrike-scan.sh";
}

function LocalSetupStep({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [rawToken, setRawToken] = useState<string | null>(null);
  const [os, setOs] = useState<LocalOs>(defaultLocalOs);
  const generate = useMutation({
    mutationFn: () => createApiKey(projectId, { label: "local CLI scan", expires_in_days: 90 }),
    onSuccess: (key) => setRawToken(key.raw_token),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to create project token"),
  });

  const token = rawToken ?? "<PROJECT_TOKEN>";
  const command = `${localInstallCmd(os, portalOrigin())}\n${localRunCmd(os, token)}`;

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
        <div className="space-y-2">
          <Label>Operating system</Label>
          <div className="flex flex-wrap gap-1 rounded-lg border border-border p-0.5">
            {LOCAL_OS.map((o) => (
              <Button
                key={o.value}
                type="button"
                size="sm"
                variant={os === o.value ? "secondary" : "ghost"}
                onClick={() => setOs(o.value)}
              >
                {o.label}
              </Button>
            ))}
          </div>
        </div>
        {rawToken ? (
          <div className="space-y-1">
            <p className="text-sm font-medium text-amber-500">
              Copy this project token now — it won&apos;t be shown again.
            </p>
            <CopyBlock text={rawToken} />
          </div>
        ) : (
          <Button type="button" onClick={() => generate.mutate()} disabled={generate.isPending}>
            {generate.isPending ? "Generating…" : "Generate a project token"}
          </Button>
        )}
        <CopyBlock label="Install & run" text={command} filename={localFilename(os)} />
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          Done
        </Button>
      </DialogFooter>
    </>
  );
}

// Runners for all three providers below default to Linux (ubuntu-latest / default GitLab image /
// Azure's ubuntu pool), so linux-amd64 is the only download target needed for v1. Windows/macOS
// CI runner variants are a documented future extension, not built now.
// Hardcoded to "latest" (YAGNI) — see localInstallCmd for the same call on the local-scan side.
function cicdInstallCmd(origin: string): string {
  return `curl -fsSL ${origin}/api/v1/downloads/zerostrike/latest/linux-amd64 -o ./zerostrike && chmod +x ./zerostrike`;
}

function cicdFilename(provider: CiProvider): string {
  if (provider === "github_actions") return "zerostrike.yml";
  if (provider === "gitlab_ci") return ".gitlab-ci.yml";
  return "azure-pipelines.yml";
}

function cicdSnippet(provider: CiProvider, origin: string): string {
  const install = cicdInstallCmd(origin);
  const cmdGh = `./zerostrike scan . --server ${origin} --token \${{ secrets.ZEROSTRIKE_TOKEN }}`;
  const cmdSh = `./zerostrike scan . --server ${origin} --token $ZEROSTRIKE_TOKEN`;
  const cmdAz = `./zerostrike scan . --server ${origin} --token $(ZEROSTRIKE_TOKEN)`;
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
      "      - name: Install ZeroStrike scanner",
      `        run: ${install}`,
      "      - name: ZeroStrike scan",
      `        run: ${cmdGh}`,
    ].join("\n");
  }
  if (provider === "gitlab_ci") {
    return [
      "# .gitlab-ci.yml",
      "zerostrike_scan:",
      "  stage: test",
      "  before_script:",
      `    - ${install}`,
      "  script:",
      `    - ${cmdSh}`,
    ].join("\n");
  }
  return [
    "# azure-pipelines.yml",
    "steps:",
    `  - script: ${install}`,
    "    displayName: Install ZeroStrike scanner",
    `  - script: ${cmdAz}`,
    "    displayName: ZeroStrike scan",
  ].join("\n");
}

function CicdSetupStep({ onDone }: { onDone: () => void }) {
  const [provider, setProvider] = useState<CiProvider>();

  return (
    <>
      <DialogHeader>
        <DialogTitle>CI/CD scan</DialogTitle>
        <DialogDescription>
          Add ZeroStrike to your pipeline. Store a project token as a secret named{" "}
          <code>ZEROSTRIKE_TOKEN</code> (generate one on the Project Tokens tab), then drop in the snippet.
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
        {provider && (
          <div className="space-y-1">
            <CopyBlock
              label="Pipeline snippet"
              text={cicdSnippet(provider, portalOrigin())}
              filename={cicdFilename(provider)}
            />
            {provider === "github_actions" && (
              <p className="text-xs text-muted-foreground">
                Save the downloaded file as <code>.github/workflows/zerostrike.yml</code>.
              </p>
            )}
          </div>
        )}
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
  const { data: projectRepos } = useQuery({
    queryKey: ["projects", projectId, "repos"],
    queryFn: () => listProjectRepos(projectId),
  });
  const [source, setSource] = useState<"connected" | "manual">("manual");
  const [selectedRepoId, setSelectedRepoId] = useState<string>("");
  const hasConnectedRepos = !!projectRepos?.length;

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<NewCloudScanInput>({ resolver: zodResolver(newCloudScanSchema) });

  // Once connected repos load, default to that tab so the common case (a repo is already set up)
  // doesn't require an extra click.
  if (hasConnectedRepos && source === "manual" && !selectedRepoId) {
    setSource("connected");
  }

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

  function selectConnectedRepo(repo: ProjectRepo) {
    setSelectedRepoId(repo.id);
    setValue("project_repo_id", repo.id, { shouldValidate: true });
    setValue("repo_url", undefined);
  }

  const selectedRepo = projectRepos?.find((r) => r.id === selectedRepoId);
  const needsRepoSelection = source === "connected" && !selectedRepoId;

  return (
    <form onSubmit={handleSubmit((values) => mutation.mutate(values))}>
      <DialogHeader>
        <DialogTitle>Cloud scan</DialogTitle>
        <DialogDescription>
          ZeroStrike clones the repository and scans it on the server. Use a repo already connected on
          the Repositories tab, or provide a URL and token for a one-off scan.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        {hasConnectedRepos && (
          <Tabs
            value={source}
            onValueChange={(value) => {
              setSource(value as typeof source);
              setSelectedRepoId("");
              setValue("project_repo_id", undefined);
              setValue("repo_url", undefined);
              setValue("repo_token", "");
            }}
          >
            <TabsList>
              <TabsTrigger value="connected">Use connected repo</TabsTrigger>
              <TabsTrigger value="manual">Manual URL</TabsTrigger>
            </TabsList>
          </Tabs>
        )}

        {source === "connected" && hasConnectedRepos ? (
          <div className="space-y-2">
            <Label>Repository</Label>
            <Select
              value={selectedRepoId}
              onValueChange={(value) => {
                const repo = projectRepos?.find((r) => r.id === value);
                if (repo) selectConnectedRepo(repo);
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Choose a connected repo…" />
              </SelectTrigger>
              <SelectContent>
                {projectRepos?.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.label ? `${r.label} — ${r.repo_full_name}` : r.repo_full_name} ({r.selected_branch})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedRepo && (
              <p className="text-xs text-muted-foreground">
                Branch: <code>{selectedRepo.selected_branch}</code>. Change it on the Repositories tab.
              </p>
            )}
          </div>
        ) : (
          <>
            <div className="space-y-2">
              <Label htmlFor="cloud-repo">Repository URL</Label>
              <Input
                id="cloud-repo"
                placeholder="https://github.com/org/repo"
                autoComplete="off"
                {...register("repo_url")}
              />
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
          </>
        )}
        <div className="space-y-2">
          <Label htmlFor="cloud-label">Label (optional)</Label>
          <Input id="cloud-label" autoComplete="off" {...register("scan_label")} />
        </div>
      </div>
      <DialogFooter>
        <Button type="submit" disabled={mutation.isPending || needsRepoSelection}>
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
          <CicdSetupStep onDone={close} />
        ) : (
          <TypeSelectStep onSelect={setScanType} />
        )}
      </DialogContent>
    </Dialog>
  );
}
