"use client";

import { Wand2 } from "lucide-react";
import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ProjectAutoFixSection() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>Auto-Fix</CardTitle>
          <Badge variant="secondary">In development</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <EmptyState
          icon={Wand2}
          title="In development"
          description="AI-generated fix proposals with confidence scoring — you'll review every diff before anything is applied. Nothing auto-commits."
        />
      </CardContent>
    </Card>
  );
}
