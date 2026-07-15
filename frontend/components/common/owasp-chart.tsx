"use client";

import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { EmptyState } from "@/components/common/empty-state";
import type { OwaspCategoryCount } from "@/lib/owasp";

const chartConfig: ChartConfig = {
  count: { label: "Findings", color: "var(--primary)" },
};

export function OwaspChart({
  data,
  activeCategory,
  onSelectCategory,
}: {
  data: OwaspCategoryCount[];
  activeCategory?: string;
  onSelectCategory?: (code: string) => void;
}) {
  if (data.every((d) => d.count === 0)) {
    return <EmptyState title="No OWASP-categorized findings yet" />;
  }

  return (
    <ChartContainer config={chartConfig} className="h-[280px] w-full">
      <BarChart data={data} layout="vertical" margin={{ left: 8 }}>
        <CartesianGrid horizontal={false} strokeDasharray="3 3" />
        <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} />
        <YAxis type="category" dataKey="code" tickLine={false} axisLine={false} width={64} fontSize={12} />
        <ChartTooltip
          content={<ChartTooltipContent labelFormatter={(_, payload) => payload?.[0]?.payload?.title ?? ""} />}
        />
        <Bar dataKey="count" radius={4}>
          {data.map((d) => (
            <Cell
              key={d.code}
              className={onSelectCategory ? "cursor-pointer" : undefined}
              onClick={() => onSelectCategory?.(d.code)}
              fill={!activeCategory || activeCategory === d.code ? "var(--color-count)" : "var(--muted)"}
            />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
