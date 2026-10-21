import { IntegrationsSubNav } from "@/components/settings/integrations/sub-nav";

export default function IntegrationsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Integrations</h2>
        <p className="text-sm text-muted-foreground">
          Everything this portal is connected to: the source-control accounts it reads from and the AI agents allowed to
          read it.
        </p>
      </div>
      <IntegrationsSubNav />
      {children}
    </div>
  );
}
