import { z } from "zod";

// Only cloud scans are created through a form. Local and CI/CD scans are produced
// by the scanner itself (via API key), so the dialog shows setup instructions for
// those rather than a create form.
export const newCloudScanSchema = z.object({
  repo_url: z.string().url("Enter a valid repository URL"),
  branch: z.string().optional(),
  scan_label: z.string().optional(),
  repo_token: z.string().optional(),
  // Set instead of repo_token when the repo was picked from a connected GitHub/Azure DevOps
  // account — resolved to a real credential server-side (see connection_service).
  connection_id: z.string().optional(),
});
export type NewCloudScanInput = z.infer<typeof newCloudScanSchema>;
