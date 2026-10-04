import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { KeyStorageBadge } from "./key-storage-badge";

describe("KeyStorageBadge", () => {
  test("key_vault shows the badge and the secret name", () => {
    render(<KeyStorageBadge storage="key_vault" secretName="ai-key-abc" />);
    expect(screen.getByText("Azure Key Vault")).toBeDefined();
    expect(screen.getByText("ai-key-abc")).toBeDefined();
    expect(screen.getByTitle("Stored in Azure Key Vault as ai-key-abc")).toBeDefined();
  });

  test("encrypted_database shows a muted badge with the migration hint", () => {
    render(<KeyStorageBadge storage="encrypted_database" />);
    expect(screen.getByText("Database (encrypted)")).toBeDefined();
    expect(screen.getByTitle(/Not in Key Vault yet/)).toBeDefined();
  });

  test("none renders nothing", () => {
    const { container } = render(<KeyStorageBadge storage="none" />);
    expect(container.innerHTML).toBe("");
  });
});
