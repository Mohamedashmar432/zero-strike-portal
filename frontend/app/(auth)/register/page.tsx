"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { safeNextPath } from "@/lib/safe-redirect";
import { registerSchema, type RegisterInput } from "@/lib/validation/auth.schema";
import { useAuth } from "@/providers/auth-provider";

function RegisterForm() {
  const { register: registerUser, isAuthenticating } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const inviteToken = searchParams.get("invite_token");
  const invitedEmail = searchParams.get("email");
  // Where a signed-out visitor was heading (an alert link); carried through to sign-in and back.
  const next = safeNextPath(searchParams.get("next"));
  const nextQuery = next ? `?next=${encodeURIComponent(next)}` : "";
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RegisterInput>({
    resolver: zodResolver(registerSchema),
    defaultValues: invitedEmail ? { email: invitedEmail } : undefined,
  });

  async function onSubmit(values: RegisterInput) {
    try {
      const created = await registerUser(values.email, values.password, values.name, inviteToken);
      if (created.approval_status === "pending") {
        setSubmittedEmail(created.email);
        return;
      }
      router.push(next ?? "/dashboard");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Registration failed");
    }
  }

  if (submittedEmail) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Request received</CardTitle>
          <CardDescription>Your account is awaiting administrator approval.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            An administrator will review your request. We&apos;ll email {submittedEmail} as soon as
            a decision is made, and you can sign in after your access is approved.
          </p>
          <Link href={`/login${nextQuery}`} className="text-foreground underline underline-offset-4">
            Back to sign in
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create an account</CardTitle>
        <CardDescription>
          {next
            ? "Create an account to open this report. You will also need to be a member of the project."
            : "Start scanning your projects with thinkShield."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" autoComplete="name" {...register("name")} />
            {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="email" placeholder="you@thinkbridge.in" {...register("email")} />
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" autoComplete="new-password" {...register("password")} />
            {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
          </div>
          <Button type="submit" className="w-full" disabled={isAuthenticating}>
            {isAuthenticating ? "Creating account…" : "Create account"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href={`/login${nextQuery}`} className="text-foreground underline underline-offset-4">
            Sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterForm />
    </Suspense>
  );
}
