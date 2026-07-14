import { Sparkles } from "lucide-react";
import { EmptyState } from "@/components/common/empty-state";

export default function AiProviderSettingsPage() {
  return (
    <div className="max-w-md space-y-6">
      <div>
        <h2 className="text-lg font-semibold">AI Provider</h2>
        <p className="text-sm text-muted-foreground">Configure the AI engine used for finding analysis.</p>
      </div>
      <EmptyState icon={Sparkles} title="Coming soon" description="AI-assisted analysis isn't available yet." />
    </div>
  );
}
