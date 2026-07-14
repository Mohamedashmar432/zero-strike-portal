"use client";

import { toast } from "sonner";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { Provider } from "@/lib/api/repo-credentials";
import { AzureDevOpsIcon, BitbucketIcon, GitHubIcon, GitLabIcon } from "@/components/repos/provider-icons";

const PROVIDERS: {
  value: Provider | "gitlab" | "bitbucket";
  label: string;
  icon: typeof GitHubIcon;
  available: boolean;
}[] = [
  { value: "github", label: "GitHub", icon: GitHubIcon, available: true },
  { value: "azure_devops", label: "Azure DevOps", icon: AzureDevOpsIcon, available: true },
  { value: "gitlab", label: "GitLab", icon: GitLabIcon, available: false },
  { value: "bitbucket", label: "Bitbucket", icon: BitbucketIcon, available: false },
];

export function ProviderPicker({ onSelect }: { onSelect: (provider: Provider) => void }) {
  return (
    <div className="space-y-2">
      <Label>Source code provider</Label>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {PROVIDERS.map((p) => (
          <button
            key={p.value}
            type="button"
            onClick={() => {
              if (!p.available) {
                toast(`${p.label} integration is coming soon`);
                return;
              }
              onSelect(p.value as Provider);
            }}
            className={cn(
              "flex flex-col items-center gap-2 rounded-md border border-border p-4 text-center transition-colors hover:border-primary/50 hover:bg-accent",
              !p.available && "opacity-60"
            )}
          >
            <p.icon className="size-7" />
            <span className="text-sm font-medium text-foreground">{p.label}</span>
            {!p.available && (
              <span className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
                Coming soon
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
