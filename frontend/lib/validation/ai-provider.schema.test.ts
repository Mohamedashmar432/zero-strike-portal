import { describe, expect, test } from "vitest";
import { aiProviderFormSchema } from "./ai-provider.schema";

describe("aiProviderFormSchema", () => {
  test("accepts a hosted provider without a base_url", () => {
    const result = aiProviderFormSchema.safeParse({
      name: "Prod Anthropic",
      provider: "anthropic",
      model_name: "claude-sonnet-5",
    });
    expect(result.success).toBe(true);
  });

  test.each(["lmstudio", "custom"] as const)("rejects %s without a base_url", (provider) => {
    const result = aiProviderFormSchema.safeParse({
      name: "Local",
      provider,
      model_name: "local-model",
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toEqual(["base_url"]);
    }
  });

  test.each(["lmstudio", "custom"] as const)("accepts %s once a base_url is set", (provider) => {
    const result = aiProviderFormSchema.safeParse({
      name: "Local",
      provider,
      model_name: "local-model",
      base_url: "http://localhost:1234/v1",
    });
    expect(result.success).toBe(true);
  });

  test("rejects a blank base_url (whitespace only) for a self-hosted provider", () => {
    const result = aiProviderFormSchema.safeParse({
      name: "Local",
      provider: "custom",
      model_name: "local-model",
      base_url: "   ",
    });
    expect(result.success).toBe(false);
  });

  test("rejects an empty model name", () => {
    const result = aiProviderFormSchema.safeParse({
      name: "Prod",
      provider: "anthropic",
      model_name: "",
    });
    expect(result.success).toBe(false);
  });

  test("rejects a missing or blank name", () => {
    const missing = aiProviderFormSchema.safeParse({
      provider: "anthropic",
      model_name: "claude-sonnet-5",
    });
    expect(missing.success).toBe(false);

    const blank = aiProviderFormSchema.safeParse({
      name: "",
      provider: "anthropic",
      model_name: "claude-sonnet-5",
    });
    expect(blank.success).toBe(false);
  });

  test("api_key and base_url are optional for hosted providers", () => {
    const result = aiProviderFormSchema.safeParse({
      name: "Prod OpenAI",
      provider: "openai",
      model_name: "gpt-5",
    });
    expect(result.success).toBe(true);
  });
});
