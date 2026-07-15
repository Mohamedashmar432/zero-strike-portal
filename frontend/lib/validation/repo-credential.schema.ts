import { z } from "zod";

export const repoCredentialSchema = z
  .object({
    provider: z.enum(["github", "azure_devops"]),
    pat: z.string().min(1, "Personal access token is required"),
    organization: z.string().min(1, "Organization is required"),
    ado_project: z.string().optional(),
    label: z.string().optional(),
  })
  .refine((v) => v.provider !== "azure_devops" || !!v.ado_project, {
    message: "Azure DevOps project is required",
    path: ["ado_project"],
  });
export type RepoCredentialInput = z.infer<typeof repoCredentialSchema>;

export const reauthRepoSchema = z.object({
  pat: z.string().min(1, "Token is required"),
});
export type ReauthRepoInput = z.infer<typeof reauthRepoSchema>;
