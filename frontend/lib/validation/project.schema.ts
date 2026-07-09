import { z } from "zod";

export const createProjectSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
});
export type CreateProjectInput = z.infer<typeof createProjectSchema>;

export const inviteMemberSchema = z.object({
  email: z.string().email(),
});
export type InviteMemberInput = z.infer<typeof inviteMemberSchema>;

export const createApiKeySchema = z.object({
  label: z.string().min(1, "Label is required"),
  expires_in_days: z.number().int().min(1).max(365),
});
export type CreateApiKeyInput = z.infer<typeof createApiKeySchema>;
