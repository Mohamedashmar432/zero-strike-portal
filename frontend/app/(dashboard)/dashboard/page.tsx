import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SeverityBadge } from "@/components/severity/severity-badge";

const stats = [
  { label: "Projects", value: 0 },
  { label: "Scans", value: 0 },
  { label: "Critical Findings", value: 0, severity: "critical" as const },
  { label: "High Findings", value: 0, severity: "high" as const },
];

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-normal text-muted-foreground">{stat.label}</CardTitle>
            </CardHeader>
            <CardContent className="flex items-center gap-2">
              <span className="font-mono text-2xl font-semibold">{stat.value}</span>
              {stat.severity && <SeverityBadge severity={stat.severity} />}
            </CardContent>
          </Card>
        ))}
      </div>
      <p className="text-sm text-muted-foreground">
        Recent scans and latest reports will appear here once Sprint 2/3 project + scan features land.
      </p>
    </div>
  );
}
