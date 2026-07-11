import { PageHeader } from "@/components/layout/page-header";
import { SettingsNav } from "@/components/layout/settings-nav";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" />
      <div className="flex flex-col gap-6 md:flex-row">
        <div className="md:w-48 md:shrink-0">
          <SettingsNav />
        </div>
        <div className="flex-1">{children}</div>
      </div>
    </div>
  );
}
