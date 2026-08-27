"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { OctagonAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, NetworkError } from "@/lib/api/client";
import { loginSchema, type LoginInput } from "@/lib/validation/auth.schema";
import { useAuth } from "@/providers/auth-provider";

export default function LoginPage() {
  const { login, isAuthenticating } = useAuth();
  const router = useRouter();
  // A toast is dismissable and easy to miss — a failed sign-in needs feedback
  // that stays on screen next to the form until you act on it.
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginInput>({ resolver: zodResolver(loginSchema) });

  async function onSubmit(values: LoginInput) {
    setFormError(null);
    try {
      await login(values.email, values.password);
      router.push("/dashboard");
    } catch (err) {
      // Three genuinely different failures. Collapsing them into "Login failed"
      // sends people hunting for a password problem when the backend is simply
      // not running on the port NEXT_PUBLIC_API_BASE_URL points at.
      const message =
        err instanceof NetworkError
          ? err.message
          : err instanceof ApiError
            ? err.status === 401
              ? "Invalid email or password."
              : err.message
            : "Sign-in failed for an unexpected reason.";
      setFormError(message);
      toast.error(message);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Authenticate</CardTitle>
        <CardDescription className="text-[13px]">
          Access your projects, scans and findings.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {formError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-sm border-l-2 border-severity-critical bg-severity-critical-tint px-2.5 py-2"
            >
              <OctagonAlert
                className="mt-px size-3.5 shrink-0 text-severity-critical"
                aria-hidden="true"
              />
              <p className="font-mono text-[11px] leading-relaxed text-severity-critical">
                {formError}
              </p>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="email" className="legend text-muted-foreground">
              Email
            </Label>
            <Input id="email" type="email" autoComplete="email" {...register("email")} />
            {errors.email && (
              <p className="font-mono text-[11px] text-destructive">{errors.email.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <div className="flex items-baseline justify-between">
              <Label htmlFor="password" className="legend text-muted-foreground">
                Password
              </Label>
              <Link
                href="/forgot-password"
                className="font-mono text-[11px] text-muted-foreground underline-offset-4 transition-colors hover:text-signal hover:underline"
              >
                Forgot?
              </Link>
            </div>
            <Input id="password" type="password" autoComplete="current-password" {...register("password")} />
            {errors.password && (
              <p className="font-mono text-[11px] text-destructive">{errors.password.message}</p>
            )}
          </div>
          <Button type="submit" size="lg" className="w-full" disabled={isAuthenticating}>
            {isAuthenticating ? "Signing in…" : "Sign in"}
          </Button>
        </form>
        <p className="mt-5 border-t border-hairline pt-4 text-center font-mono text-[11px] text-muted-foreground">
          No account?{" "}
          <Link
            href="/register"
            className="text-foreground underline underline-offset-4 transition-colors hover:text-signal"
          >
            Register
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
