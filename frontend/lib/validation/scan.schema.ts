import { z } from "zod";

export const newLocalScanSchema = z.object({
  scan_label: z.string().optional(),
});
export type NewLocalScanInput = z.infer<typeof newLocalScanSchema>;

export const newCloudScanSchema = z.object({
  scan_label: z.string().optional(),
  repo_url: z.string().url("Enter a valid repository URL"),
});
export type NewCloudScanInput = z.infer<typeof newCloudScanSchema>;

export const newCicdScanSchema = z.object({
  scan_label: z.string().optional(),
  ci_provider: z.enum(["github_actions", "gitlab_ci", "azure_pipelines"], {
    message: "Choose a CI provider",
  }),
});
export type NewCicdScanInput = z.infer<typeof newCicdScanSchema>;
