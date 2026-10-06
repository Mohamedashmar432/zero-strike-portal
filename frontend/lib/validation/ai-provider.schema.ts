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
  "groq",
  "gemini",
  "deepseek",
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
    // USD per 1M tokens; blank = use the price list.
    input_cost: z.string().optional(),
    output_cost: z.string().optional(),
  })
  .refine((v) => !SELF_HOSTED_PROVIDERS.includes(v.provider) || !!v.base_url?.trim(), {
    message: "Base URL is required for this provider",
    path: ["base_url"],
  })
  .refine((v) => !v.input_cost?.trim() || Number(v.input_cost) >= 0, {
    message: "Must be a number of 0 or more",
    path: ["input_cost"],
  })
  .refine((v) => !v.output_cost?.trim() || Number(v.output_cost) >= 0, {
    message: "Must be a number of 0 or more",
    path: ["output_cost"],
  });
export type AiProviderFormValues = z.infer<typeof aiProviderFormSchema>;
