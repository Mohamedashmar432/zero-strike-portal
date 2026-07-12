"use client";

import { Cell, Pie, PieChart } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { EmptyState } from "@/components/common/empty-state";
import { ShieldCheck } from "lucide-react";
import type { Severity } from "@/lib/api/findings";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];

const chartConfig: ChartConfig = {
  critical: { label: "Critical", color: "var(--severity-critical)" },
  high: { label: "High", color: "var(--severity-high)" },
  medium: { label: "Medium", color: "var(--severity-medium)" },
  low: { label: "Low", color: "var(--severity-low)" },
  info: { label: "Info", color: "var(--severity-info)" },
};

type SeverityCounts = Record<Severity, number>;

export function SeverityDistributionChart({ data }: { data: SeverityCounts }) {
  const total = SEVERITIES.reduce((sum, severity) => sum + data[severity], 0);

  if (total === 0) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="No findings yet"
        description="Run a scan to see your severity distribution here."
      />
    );
  }

  const chartData = SEVERITIES.map((severity) => ({ severity, count: data[severity] }));

  return (
    <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
      <ChartContainer config={chartConfig} className="mx-auto aspect-square max-h-[220px]">
        <PieChart>
          <ChartTooltip cursor={false} content={<ChartTooltipContent nameKey="severity" hideLabel />} />
          <Pie data={chartData} dataKey="count" nameKey="severity" innerRadius={55} outerRadius={85} paddingAngle={2}>
            {chartData.map((entry) => (
              <Cell key={entry.severity} fill={`var(--severity-${entry.severity})`} />
            ))}
          </Pie>
        </PieChart>
      </ChartContainer>
      <div className="flex flex-col gap-2">
        {SEVERITIES.map((severity) => (
          <div key={severity} className="flex items-center gap-2 text-sm">
            <SeverityBadge severity={severity} />
            <span className="font-mono">{data[severity]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
