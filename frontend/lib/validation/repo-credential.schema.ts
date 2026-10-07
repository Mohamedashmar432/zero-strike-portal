import { z } from "zod";

// Accepts a pasted "https://dev.azure.com/<org>/..." or legacy "<org>.visualstudio.com" URL and keeps
// just the org — that segment is all the backend puts in the API URL.
export function normalizeAdoOrganization(input: string): string {
  const v = input.trim();
  const devAzure = v.match(/^(?:https?:\/\/)?dev\.azure\.com\/([^/?#]+)/i);
  if (devAzure) return decodeURIComponent(devAzure[1]);
  const vsts = v.match(/^(?:https?:\/\/)?([^./]+)\.visualstudio\.com/i);
  return vsts ? vsts[1] : v;
}

// An Azure DevOps credential is org-wide: no project here, it is picked when connecting a repo.
export const repoCredentialSchema = z.object({
  provider: z.enum(["github", "azure_devops"]),
  pat: z.string().trim().min(1, "Personal access token is required"),
  organization: z.string().trim().min(1, "Organization is required"),
  label: z.string().optional(),
});
export type RepoCredentialInput = z.infer<typeof repoCredentialSchema>;

export const reauthRepoSchema = z.object({
  pat: z.string().min(1, "Token is required"),
});
export type ReauthRepoInput = z.infer<typeof reauthRepoSchema>;
