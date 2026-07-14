import { Bell } from "lucide-react";
import { EmptyState } from "@/components/common/empty-state";

export default function NotificationSettingsPage() {
  return (
    <div className="max-w-md space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Notifications</h2>
        <p className="text-sm text-muted-foreground">Choose when the portal notifies you.</p>
      </div>
      <EmptyState icon={Bell} title="Coming soon" description="Notification preferences aren't available yet." />
    </div>
  );
}
