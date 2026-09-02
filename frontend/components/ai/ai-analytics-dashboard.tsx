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
  LLM_ERROR_LABELS,
  type AiAnalytics,
  type AiEventFilters,
  type AiUsageTotals,
} from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";
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

/**
 * Keeps both ends of a label. Truncating only the tail made "claude-sonnet-4-5" and
 * "claude-haiku-4-5" render identically on the axis, which reads as a duplicated bar.
 */
function middleTruncate(value: string, max = 26) {
  if (value.length <= max) return value;
  const head = Math.ceil((max - 1) / 2);
  return `${value.slice(0, head)}…${value.slice(-(max - 1 - head))}`;
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
            {/* by_feature also carries zero-cost rows for features that spent only in the
                previous window -- those belong in "What changed", not in a bar chart of zeroes. */}
            <BreakdownCard
              title="Spend by feature"
              description="Which AI feature the money went to."
              rows={data!.by_feature
                .filter((r) => r.requests > 0)
                .map((r) => ({ label: featureLabel(r.feature), ...r }))}
            />
            <SpendMovementCard data={data!} />
            <FailureReasonsCard data={data!} />
            <BreakdownCard
              title="Spend by model"
              description="Cost per model. Hover for the provider."
              // Label on the model, not "provider · model": the provider repeats across rows, so
              // prefixing it pushed the distinguishing part past the truncation point and rendered
              // claude-sonnet-4-5 and claude-haiku-4-5 as the same string. Provider is in the tooltip.
              rows={data!.by_model.map((r) => ({
                label: r.model_name || r.provider,
                sublabel: r.provider,
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
        features={data?.by_feature.filter((f) => f.requests > 0).map((f) => f.feature) ?? []}
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
/**
 * What moved, and which workflow moved it.
 *
 * "Spend by feature" says where the money went; it does not say why the bill changed. This
 * compares each feature against the equally-long window immediately before, largest movement
 * first, so a jump resolves to a workflow instead of staying a mystery.
 */
function SpendMovementCard({ data }: { data: AiAnalytics }) {
  const moved = data.by_feature
    .filter((r) => Math.abs(r.cost_delta_usd ?? 0) > 0 || (r.requests_delta ?? 0) !== 0)
    .sort((a, b) => Math.abs(b.cost_delta_usd ?? 0) - Math.abs(a.cost_delta_usd ?? 0))
    .slice(0, 6);

  const totalDelta = (data.totals.cost_usd ?? 0) - (data.previous_totals?.cost_usd ?? 0);
  const driver = moved[0];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">What changed</CardTitle>
        <p className="text-sm text-muted-foreground">
          {totalDelta === 0
            ? `Spend is flat against the previous ${data.days} days.`
            : `Spend is ${totalDelta > 0 ? "up" : "down"} ${usd(Math.abs(totalDelta))} against the previous ${data.days} days` +
              (driver ? ` — mostly ${featureLabel(driver.feature)}.` : ".")}
        </p>
      </CardHeader>
      <CardContent>
        {moved.length === 0 ? (
          <EmptyState title="No movement to explain" />
        ) : (
          <ul className="divide-y divide-hairline">
            {moved.map((row) => {
              const delta = row.cost_delta_usd ?? 0;
              const up = delta > 0;
              return (
                <li
                  key={row.feature}
                  className="flex items-baseline justify-between gap-3 py-2 text-sm"
                >
                  <span className="min-w-0 truncate">{featureLabel(row.feature)}</span>
                  <span className="flex shrink-0 items-baseline gap-3 font-mono text-xs tabular-nums">
                    <span className="text-muted-foreground">
                      {usd(row.prev_cost_usd ?? 0)} → {usd(row.cost_usd)}
                    </span>
                    <span
                      className={cn(
                        "w-20 text-right",
                        delta === 0
                          ? "text-muted-foreground"
                          : up
                            ? "text-severity-medium"
                            : "text-status-success",
                      )}
                    >
                      {up ? "+" : "−"}
                      {usd(Math.abs(delta))}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function FailureReasonsCard({ data }: { data: AiAnalytics }) {
  const rows = data.failure_reasons;
  // Nothing failed: a card of zeroes is noise on a healthy workspace.
  if (rows.length === 0) return null;

  const worst = rows[0].count;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Why calls failed</CardTitle>
        <p className="text-sm text-muted-foreground">
          {data.totals.failed} failed {data.totals.failed === 1 ? "call" : "calls"} in this window,
          by cause.
        </p>
      </CardHeader>
      <CardContent>
        {/* A ranked list, not a bar chart: at most a dozen categories with a one-line label each,
            where the label is the actionable part and a chart would only shrink it. */}
        <ul className="space-y-2.5">
          {rows.map((r) => (
            <li key={r.error_code}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="truncate">{LLM_ERROR_LABELS[r.error_code] ?? r.error_code}</span>
                <span className="tabular-nums text-muted-foreground">{compact(r.count)}</span>
              </div>
              <div
                className="mt-1 h-1.5 rounded-full bg-destructive/70"
                style={{ width: `${Math.max(4, (r.count / worst) * 100)}%` }}
                aria-hidden
              />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}


function BreakdownCard({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: { label: string; sublabel?: string; cost_usd: number; requests: number }[];
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
                width={170}
                // Ellipsis in the middle, not the end: these labels (model ids, project names)
                // differ in their tails far more often than their heads. Wrapped in an arrow on
                // purpose -- recharts calls tickFormatter with (value, index), and passing
                // middleTruncate directly would bind the tick index to its `max` parameter.
                tickFormatter={(v: string) => middleTruncate(v)}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(_label, payload) => {
                      const row = payload?.[0]?.payload;
                      return row?.sublabel ? `${row.label} · ${row.sublabel}` : (row?.label ?? "");
                    }}
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
                          {/* The classified reason where there is one -- "Invalid API key" is
                              something an admin can act on, "LLMPermanentError" is not. */}
                          {e.error_code
                            ? (LLM_ERROR_LABELS[e.error_code] ?? e.error_code)
                            : (e.error_type ?? "Failed")}
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
