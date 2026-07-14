import { Settings } from "lucide-react";
import { EmptyState } from "@/components/common/empty-state";

export default function GeneralSettingsPage() {
  return (
    <div className="max-w-md space-y-6">
      <div>
        <h2 className="text-lg font-semibold">General</h2>
        <p className="text-sm text-muted-foreground">Workspace-wide scan defaults and preferences.</p>
      </div>
      <EmptyState
        icon={Settings}
        title="Coming soon"
        description="Workspace-level scan configuration isn't available yet."
      />
    </div>
  );
}
