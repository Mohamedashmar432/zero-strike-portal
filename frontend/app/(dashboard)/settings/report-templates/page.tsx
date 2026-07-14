import { FileText } from "lucide-react";
import { EmptyState } from "@/components/common/empty-state";

export default function ReportTemplatesSettingsPage() {
  return (
    <div className="max-w-md space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Report Templates</h2>
        <p className="text-sm text-muted-foreground">Customize the layout and branding of generated PDF reports.</p>
      </div>
      <EmptyState icon={FileText} title="Coming soon" description="Custom report templates aren't available yet." />
    </div>
  );
}
