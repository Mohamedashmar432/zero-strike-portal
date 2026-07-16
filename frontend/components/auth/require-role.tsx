"use client";

import type { ReactNode } from "react";
import type { User } from "@/lib/api/auth";
import { useHasRole } from "@/lib/hooks/use-has-role";

/**
 * Renders children only if the current user has the given role. Client-side only --
 * hides UI, it doesn't enforce access. The backend must independently reject any
 * request this gates from a non-matching role.
 */
export function RequireRole({ role, children }: { role: User["role"]; children: ReactNode }) {
  if (!useHasRole(role)) return null;
  return <>{children}</>;
}
