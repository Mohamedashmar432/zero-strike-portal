import { Wand2 } from "lucide-react";
import { EmptyState } from "@/components/common/empty-state";

export default function AutoFixSettingsPage() {
  return (
    <div className="max-w-md space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Auto-fix</h2>
        <p className="text-sm text-muted-foreground">Automatic remediation suggestions for findings.</p>
      </div>
      <EmptyState icon={Wand2} title="Coming soon" description="Auto-fix isn't available yet." />
    </div>
  );
}
