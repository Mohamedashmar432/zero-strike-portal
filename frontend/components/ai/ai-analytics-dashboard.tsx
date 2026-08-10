"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, TriangleAlert } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  getPortalAiAnalytics,
  getProjectAiAnalytics,
  listPortalAiEvents,
  listProjectAiEvents,
  type AiAnalytics,
  type AiEventFilters,
  type AiUsageTotals,
} from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/common/empty-state";
import { StatCard } from "@/components/common/stat-card";

const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

/**
 * The metric the time series plots. A toggle rather than three stacked charts, and rather than
 * a second y-axis — cost and request counts differ by orders of magnitude, and a dual-axis chart
 * makes their crossings look meaningful when they are an artifact of the two scales.
 */
const METRICS = [
  { value: "cost_usd", label: "Cost" },
  { value: "requests", label: "Requests" },
  { value: "prompt_tokens", label: "Tokens in" },
  { value: "completion_tokens", label: "Tokens out" },
] as const;

type Metric = (typeof METRICS)[number]["value"];

const PAGE_SIZE = 15;

// Labels for the feature slugs llm_client stamps on each call.
const FEATURE_LABELS: Record<string, string> = {
  analysis: "Finding analysis",
  scan_synthesis: "Scan summary",
  autofix: "Auto-fix agent",
  critic: "Auto-fix critic",
  compliance: "Compliance narrative",
  repo_doc: "Repo summary",
  fix_chat: "Fix Q&A",
  unknown: "Other",
};

function featureLabel(feature: string) {
  return FEATURE_LABELS[feature] ?? feature;
}

function usd(value: number) {
  // Sub-cent spend is normal on cheap models; $0.00 for a real call reads as "free" or broken.
  if (value > 0 && value < 0.01) return "<$0.01";
  return `$${value.toFixed(value < 100 ? 2 : 0)}`;
}

function compact(value: number) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(
    value,
  );
}

function duration(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function metricValue(row: Record<string, number>, metric: Metric) {
  return row[metric] ?? 0;
}

function formatMetric(value: number, metric: Metric) {
  return metric === "cost_usd" ? usd(value) : compact(value);
}

export function AiAnalyticsDashboard({
  scope,
  projectId,
}: {
  scope: "project" | "portal";
  projectId?: string;
}) {
  const [days, setDays] = useState(30);
  const [metric, setMetric] = useState<Metric>("cost_usd");
  const [feature, setFeature] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  const [page, setPage] = useState(1);

  const analytics = useQuery({
    queryKey:
      scope === "project"
        ? queryKeys.projects.aiAnalytics(projectId!, days)
        : queryKeys.ai.portalAnalytics(days),
    queryFn: () =>
      scope === "project" ? getProjectAiAnalytics(projectId!, days) : getPortalAiAnalytics(days),
  });

  const eventFilters: AiEventFilters = {
    days,
    page,
    page_size: PAGE_SIZE,
    feature: feature === "all" ? undefined : feature,
    status: status === "all" ? undefined : (status as "success" | "failed"),
  };
  const events = useQuery({
    queryKey:
      scope === "project"
        ? queryKeys.projects.aiEvents(projectId!, eventFilters)
        : queryKeys.ai.portalEvents(eventFilters),
    queryFn: () =>
      scope === "project"
        ? listProjectAiEvents(projectId!, eventFilters)
        : listPortalAiEvents(eventFilters),
  });

  const data = analytics.data;
  const hasData = (data?.totals.requests ?? 0) > 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">AI usage</h2>
          <p className="text-sm text-muted-foreground">
            {scope === "portal"
              ? "Every LLM call made across all projects."
              : "Every LLM call made for this project."}
          </p>
        </div>
        <Select value={String(days)} onValueChange={(v) => setDays(Number(v ?? 30))}>
          <SelectTrigger className="w-40" aria-label="Time range">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RANGES.map((r) => (
              <SelectItem key={r.value} value={r.value}>
                {r.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <KpiRow totals={data?.totals} isLoading={analytics.isLoading} />

      {analytics.isLoading ? (
        <Skeleton className="h-[320px] w-full" />
      ) : !hasData ? (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={Activity}
              title="No AI calls in this window"
              description={
                scope === "portal"
                  ? "Once projects start running AI analysis, auto-fix or compliance audits, their spend appears here."
                  : "Run AI analysis, auto-fix or a compliance audit on a scan and its usage shows up here."
              }
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <TimeSeriesCard data={data!} metric={metric} onMetricChange={setMetric} />
          <div className="grid gap-4 lg:grid-cols-2">
            <BreakdownCard
              title="Spend by feature"
              description="Which AI feature the money went to."
              rows={data!.by_feature.map((r) => ({ label: featureLabel(r.feature), ...r }))}
            />
            <BreakdownCard
              title="Spend by model"
              description="Cost per provider and model."
              rows={data!.by_model.map((r) => ({
                label: r.model_name ? `${r.provider} · ${r.model_name}` : r.provider,
                ...r,
              }))}
            />
          </div>
          {scope === "portal" && data!.by_project.length > 0 && (
            <BreakdownCard
              title="Spend by project"
              description="Ranked by cost over the selected window."
              rows={data!.by_project.map((r) => ({ label: r.project_name, ...r }))}
            />
          )}
        </>
      )}

      <EventLogCard
        scope={scope}
        page={page}
        onPage={setPage}
        feature={feature}
        onFeature={(v) => {
          setFeature(v ?? "all");
          setPage(1);
        }}
        status={status}
        onStatus={(v) => {
          setStatus(v ?? "all");
          setPage(1);
        }}
        query={events}
        features={data?.by_feature.map((f) => f.feature) ?? []}
      />
    </div>
  );
}

function KpiRow({ totals, isLoading }: { totals?: AiUsageTotals; isLoading: boolean }) {
  const t = totals;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      <StatCard
        label="Total spend"
        value={t ? usd(t.cost_usd) : "$0.00"}
        caption="Estimated from provider pricing"
        isLoading={isLoading}
      />
      <StatCard
        label="Requests"
        value={t ? compact(t.requests) : "0"}
        caption={t && t.failed > 0 ? `${compact(t.failed)} failed` : "No failures"}
        isLoading={isLoading}
      />
      <StatCard
        label="Tokens"
        value={t ? compact(t.prompt_tokens + t.completion_tokens) : "0"}
        caption={t ? `${compact(t.prompt_tokens)} in · ${compact(t.completion_tokens)} out` : undefined}
        isLoading={isLoading}
      />
      <StatCard
        label="Success rate"
        value={t ? `${t.success_rate}%` : "—"}
        caption={t && t.failed > 0 ? "Check the log below" : "All calls succeeded"}
        isLoading={isLoading}
      />
      <StatCard
        label="Avg latency"
        value={t ? duration(t.avg_duration_ms) : "—"}
        caption="Per call, including retries"
        isLoading={isLoading}
      />
    </div>
  );
}

function TimeSeriesCard({
  data,
  metric,
  onMetricChange,
}: {
  data: AiAnalytics;
  metric: Metric;
  onMetricChange: (m: Metric) => void;
}) {
  const config: ChartConfig = {
    value: { label: METRICS.find((m) => m.value === metric)!.label, color: "var(--primary)" },
  };
  const rows = data.timeseries.map((point) => ({
    date: point.date,
    value: metricValue(point as unknown as Record<string, number>, metric),
  }));

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">Usage over time</CardTitle>
          <p className="text-sm text-muted-foreground">Daily totals, UTC.</p>
        </div>
        <div className="flex flex-wrap gap-1">
          {METRICS.map((m) => (
            <Button
              key={m.value}
              size="sm"
              variant={metric === m.value ? "secondary" : "ghost"}
              onClick={() => onMetricChange(m.value)}
            >
              {m.label}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="h-[280px] w-full">
          <AreaChart data={rows} margin={{ left: 4, right: 8, top: 8 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              minTickGap={24}
              tickFormatter={(v: string) => v.slice(5)}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={56}
              tickFormatter={(v: number) => formatMetric(v, metric)}
            />
            <ChartTooltip
              content={
                <ChartTooltipContent
                  labelFormatter={(label) => String(label)}
                  formatter={(value) => formatMetric(Number(value), metric)}
                />
              }
            />
            <Area
              dataKey="value"
              type="monotone"
              stroke="var(--color-value)"
              strokeWidth={2}
              fill="var(--color-value)"
              fillOpacity={0.12}
            />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}

/**
 * A magnitude comparison across categories, so a single mark colour is correct — the axis labels
 * carry identity, not the colour. (A categorical palette here would imply the bars are different
 * series, which they aren't.)
 */
function BreakdownCard({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: { label: string; cost_usd: number; requests: number }[];
}) {
  const config: ChartConfig = { cost_usd: { label: "Cost", color: "var(--primary)" } };
  // Keep the chart legible; the log table below is the full drill-down.
  const top = rows.slice(0, 8);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <p className="text-sm text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent>
        {top.length === 0 ? (
          <EmptyState title="Nothing recorded yet" />
        ) : (
          <ChartContainer config={config} className="h-[260px] w-full">
            <BarChart data={top} layout="vertical" margin={{ left: 8, right: 24 }}>
              <CartesianGrid horizontal={false} strokeDasharray="3 3" />
              <XAxis type="number" tickLine={false} axisLine={false} tickFormatter={usd} />
              <YAxis
                type="category"
                dataKey="label"
                tickLine={false}
                axisLine={false}
                width={140}
                tickFormatter={(v: string) => (v.length > 20 ? `${v.slice(0, 19)}…` : v)}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    formatter={(value, _name, item) =>
                      `${usd(Number(value))} · ${compact(item?.payload?.requests ?? 0)} calls`
                    }
                  />
                }
              />
              <Bar dataKey="cost_usd" fill="var(--color-cost_usd)" radius={4} barSize={18} />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}

function EventLogCard({
  scope,
  page,
  onPage,
  feature,
  onFeature,
  status,
  onStatus,
  query,
  features,
}: {
  scope: "project" | "portal";
  page: number;
  onPage: (p: number) => void;
  feature: string;
  onFeature: (v: string | null) => void;
  status: string;
  onStatus: (v: string | null) => void;
  query: ReturnType<typeof useQuery<Awaited<ReturnType<typeof listProjectAiEvents>>>>;
  features: string[];
}) {
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">AI call log</CardTitle>
          <p className="text-sm text-muted-foreground">
            Metadata only — prompts and responses are never stored.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={feature} onValueChange={onFeature}>
            <SelectTrigger className="w-44" aria-label="Filter by feature">
              <SelectValue placeholder="All features" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All features</SelectItem>
              {features.map((f) => (
                <SelectItem key={f} value={f}>
                  {featureLabel(f)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={onStatus}>
            <SelectTrigger className="w-36" aria-label="Filter by status">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="success">Succeeded</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="px-0">
        {query.isLoading ? (
          <Skeleton className="mx-6 h-40" />
        ) : items.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No calls match these filters"
            description="Widen the time range or clear the filters."
          />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  {scope === "portal" && <TableHead>Project</TableHead>}
                  <TableHead>Feature</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="text-right">Latency</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {new Date(e.created_at).toLocaleString()}
                    </TableCell>
                    {scope === "portal" && (
                      <TableCell className="max-w-[180px] truncate">
                        {e.project_name ?? "—"}
                      </TableCell>
                    )}
                    <TableCell>{featureLabel(e.feature)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {e.model_name ? `${e.provider} · ${e.model_name}` : e.provider || "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {compact(e.prompt_tokens)} / {compact(e.completion_tokens)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{usd(e.cost_usd)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {duration(e.duration_ms)}
                    </TableCell>
                    <TableCell>
                      {e.status === "success" ? (
                        <Badge variant="secondary">Succeeded</Badge>
                      ) : (
                        // Identity is never colour alone — icon + label carry it too.
                        <Badge variant="destructive" className="gap-1">
                          <TriangleAlert className="size-3" />
                          {e.error_type ?? "Failed"}
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-2 px-6 pb-4">
          <p className="text-sm text-muted-foreground">
            Page {page} of {lastPage} · {total} calls
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= lastPage}
              onClick={() => onPage(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
