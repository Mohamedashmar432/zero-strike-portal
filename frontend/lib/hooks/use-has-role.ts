import type { User } from "@/lib/api/auth";
import { useAuth } from "@/providers/auth-provider";

export function useHasRole(role: User["role"]): boolean {
  const { user } = useAuth();
  return user?.role === role;
}
