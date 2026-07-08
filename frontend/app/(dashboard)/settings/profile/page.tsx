"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";

export default function ProfilePage() {
  const { user, updateProfile } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [isSaving, setIsSaving] = useState(false);

  if (!user) return null;

  async function handleSave() {
    setIsSaving(true);
    try {
      await updateProfile(name);
      toast.success("Profile updated");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to update profile");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="max-w-md space-y-6">
      <h1 className="text-xl font-semibold">Profile</h1>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            {user.email}
            <Badge variant="secondary" className="font-mono uppercase">
              {user.role}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <Button onClick={handleSave} disabled={isSaving || name === user.name}>
            {isSaving ? "Saving…" : "Save changes"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
