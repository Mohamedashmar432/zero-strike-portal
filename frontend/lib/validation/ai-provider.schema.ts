import { z } from "zod";

// Exact provider list the backend accepts -- see lib/api/ai.ts AiProvider.
export const AI_PROVIDERS = [
  "anthropic",
  "openai",
  "lmstudio",
  "kimi",
  "nvidia_nim",
  "openrouter",
  "custom",
  "commandcode",
] as const;

// Self-hosted providers have no fixed default endpoint, so a base_url is mandatory for
// them; hosted providers (anthropic, openai, kimi, nvidia_nim, openrouter) ship a known
// default and don't need one.
const SELF_HOSTED_PROVIDERS = ["lmstudio", "custom"];

export const aiProviderFormSchema = z
  .object({
    name: z.string().min(1, "Name is required"),
    provider: z.enum(AI_PROVIDERS),
    model_name: z.string().min(1, "Model name is required"),
    api_key: z.string().optional(),
    base_url: z.string().optional(),
  })
  .refine((v) => !SELF_HOSTED_PROVIDERS.includes(v.provider) || !!v.base_url?.trim(), {
    message: "Base URL is required for this provider",
    path: ["base_url"],
  });
export type AiProviderFormValues = z.infer<typeof aiProviderFormSchema>;
