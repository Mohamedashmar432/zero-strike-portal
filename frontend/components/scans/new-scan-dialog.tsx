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
import {
  listAzureOrgs,
  listAzureProjects,
  listAzureRepos,
  listConnections,
  listGithubRepos,
  type Repo,
} from "@/lib/api/connections";
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

function SelectedRepoSummary({ repo, onChange }: { repo: Repo; onChange: () => void }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
      <span className="truncate font-mono">{repo.full_name}</span>
      <Button type="button" size="sm" variant="ghost" onClick={onChange}>
        Change
      </Button>
    </div>
  );
}

function RepoPickerList({
  repos,
  isLoading,
  isError,
  onSelect,
}: {
  repos: Repo[] | undefined;
  isLoading: boolean;
  isError: boolean;
  onSelect: (repo: Repo) => void;
}) {
  return (
    <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-1">
      {isLoading ? (
        <p className="p-2 text-sm text-muted-foreground">Loading…</p>
      ) : isError ? (
        <p className="p-2 text-sm text-destructive">
          Couldn&apos;t load repos — the connection may need to be reconnected in Settings →
          Integrations.
        </p>
      ) : repos?.length ? (
        repos.map((r) => (
          <button
            key={r.id}
            type="button"
            className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
            onClick={() => onSelect(r)}
          >
            {r.full_name}
          </button>
        ))
      ) : (
        <p className="p-2 text-sm text-muted-foreground">No repos found.</p>
      )}
    </div>
  );
}

function GithubRepoPicker({ onSelect }: { onSelect: (repo: Repo) => void }) {
  const [query, setQuery] = useState("");
  const { data: repos, isLoading, isError } = useQuery({
    queryKey: ["connections", "github", "repos", query],
    queryFn: () => listGithubRepos(query),
  });
  return (
    <div className="space-y-2">
      <Input
        placeholder="Search repos…"
        autoComplete="off"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <RepoPickerList repos={repos} isLoading={isLoading} isError={isError} onSelect={onSelect} />
    </div>
  );
}

function AzureDevOpsRepoPicker({ onSelect }: { onSelect: (repo: Repo) => void }) {
  const [org, setOrg] = useState("");
  const [project, setProject] = useState("");
  const { data: orgs } = useQuery({ queryKey: ["connections", "azure", "orgs"], queryFn: listAzureOrgs });
  const { data: projects } = useQuery({
    queryKey: ["connections", "azure", "projects", org],
    queryFn: () => listAzureProjects(org),
    enabled: !!org,
  });
  const { data: repos, isLoading, isError } = useQuery({
    queryKey: ["connections", "azure", "repos", org, project],
    queryFn: () => listAzureRepos(org, project),
    enabled: !!org && !!project,
  });

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Select
          value={org}
          onValueChange={(value) => {
            setOrg(value ?? "");
            setProject("");
          }}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Organization…" />
          </SelectTrigger>
          <SelectContent>
            {orgs?.map((o) => (
              <SelectItem key={o.id} value={o.name}>
                {o.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={project} onValueChange={(value) => setProject(value ?? "")} disabled={!org}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Project…" />
          </SelectTrigger>
          <SelectContent>
            {projects?.map((p) => (
              <SelectItem key={p.id} value={p.name}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {org && project && (
        <RepoPickerList repos={repos} isLoading={isLoading} isError={isError} onSelect={onSelect} />
      )}
    </div>
  );
}

function CloudCreateStep({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [source, setSource] = useState<"manual" | "github" | "azure_devops">("manual");
  const [selectedRepo, setSelectedRepo] = useState<Repo | null>(null);
  const { data: connections } = useQuery({ queryKey: ["connections"], queryFn: listConnections });
  const githubConnection = connections?.find((c) => c.provider === "github");
  const azureConnection = connections?.find((c) => c.provider === "azure_devops");

  const {
    register,
    handleSubmit,
    setValue,
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

  function selectRepo(repo: Repo, connectionId: string) {
    setSelectedRepo(repo);
    setValue("repo_url", repo.clone_url, { shouldValidate: true });
    setValue("connection_id", connectionId);
    setValue("repo_token", "");
    if (repo.default_branch) setValue("branch", repo.default_branch);
  }

  function clearRepoSelection() {
    setSelectedRepo(null);
    setValue("repo_url", "");
    setValue("connection_id", undefined);
  }

  const needsRepoSelection = source !== "manual" && !selectedRepo;

  return (
    <form onSubmit={handleSubmit((values) => mutation.mutate(values))}>
      <DialogHeader>
        <DialogTitle>Cloud scan</DialogTitle>
        <DialogDescription>
          ZeroStrike clones the repository and scans it on the server. Import from a connected account
          or provide a URL and token for private repos — a pasted token is used only for this clone and
          never stored.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        {(githubConnection || azureConnection) && (
          <Tabs
            value={source}
            onValueChange={(value) => {
              setSource(value as typeof source);
              clearRepoSelection();
              setValue("repo_token", "");
            }}
          >
            <TabsList>
              <TabsTrigger value="manual">Manual URL</TabsTrigger>
              {githubConnection && <TabsTrigger value="github">GitHub</TabsTrigger>}
              {azureConnection && <TabsTrigger value="azure_devops">Azure DevOps</TabsTrigger>}
            </TabsList>
          </Tabs>
        )}

        {source === "github" && githubConnection ? (
          selectedRepo ? (
            <SelectedRepoSummary repo={selectedRepo} onChange={clearRepoSelection} />
          ) : (
            <GithubRepoPicker onSelect={(r) => selectRepo(r, githubConnection.id)} />
          )
        ) : source === "azure_devops" && azureConnection ? (
          selectedRepo ? (
            <SelectedRepoSummary repo={selectedRepo} onChange={clearRepoSelection} />
          ) : (
            <AzureDevOpsRepoPicker onSelect={(r) => selectRepo(r, azureConnection.id)} />
          )
        ) : (
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
        )}
        <div className="space-y-2">
          <Label htmlFor="cloud-branch">Branch (optional)</Label>
          <Input id="cloud-branch" placeholder="main" autoComplete="off" {...register("branch")} />
        </div>
        {source === "manual" && (
          <div className="space-y-2">
            <Label htmlFor="cloud-token">Access token (private repos only)</Label>
            <Input id="cloud-token" type="password" autoComplete="off" {...register("repo_token")} />
          </div>
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
