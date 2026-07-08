import { Card, CardContent } from "@/components/ui/card";

export default function ProjectsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Projects</h1>
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          Project management lands in Sprint 2 — create projects, invite members, and issue scanner API keys.
        </CardContent>
      </Card>
    </div>
  );
}
