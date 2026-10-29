"use client";

import { MetricStrip } from "@/components/common/metric-strip";
import { SectionRule } from "@/components/layout/section-rule";
import type { ProjectInsights } from "@/lib/api/project-insights";
import { fmt } from "./date-range";

export function OverviewTab({ data, isLoading }: { data: ProjectInsights | undefined; isLoading: boolean }) {
  const t = data?.totals;
  const u = data?.users;
  const finished = t ? t.cloud.completed + t.cloud.failed + t.cicd.completed + t.cicd.failed : 0;
  const failed = t ? t.cloud.failed + t.cicd.failed : 0;
  const failureRate = finished > 0 ? (100 * failed) / finished : 0;

  return (
    <div className="space-y-6">
      <SectionRule label="People" />
      <MetricStrip
        isLoading={isLoading}
        className="lg:grid-cols-5"
        metrics={[
          {
            label: "Registered users",
            value: fmt(u?.total ?? 0),
            hint: `${fmt(u?.registered_in_window ?? 0)} in window · ${fmt(u?.registered_today ?? 0)} today (UTC)`,
            tone: "signal",
          },
          {
            label: "Active users",
            value: fmt(u?.active_in_window ?? 0),
            hint: `${fmt(u?.active_today ?? 0)} active today (UTC)`,
          },
          { label: "Never signed in", value: fmt(u?.never_signed_in ?? 0), hint: "No recorded activity yet" },
          {
            label: "Pending approval",
            value: fmt(u?.pending_approval ?? 0),
            hint: "Awaiting an admin",
            tone: (u?.pending_approval ?? 0) > 0 ? "medium" : "default",
          },
          { label: "Disabled", value: fmt(u?.disabled ?? 0), hint: "Accounts switched off" },
        ]}
      />

      <SectionRule label="Projects" />
      <MetricStrip
        isLoading={isLoading}
        className="lg:grid-cols-5"
        metrics={[
          {
            label: "Projects onboarded",
            value: fmt(t?.projects ?? 0),
            hint: `${fmt(t?.projects_created ?? 0)} new in this window`,
            tone: "signal",
          },
          { label: "Repos configured", value: fmt(t?.repos ?? 0), hint: "Connected across all projects" },
          {
            label: "Cloud scans",
            value: fmt(t?.cloud.total ?? 0),
            hint: `${fmt(t?.cloud.completed ?? 0)} completed · ${fmt(t?.cloud.failed ?? 0)} failed${
              t?.cloud.active ? ` · ${fmt(t.cloud.active)} active` : ""
            }`,
          },
          {
            label: "Pipeline runs",
            value: fmt(t?.cicd.total ?? 0),
            hint: `${fmt(t?.cicd.completed ?? 0)} completed · ${fmt(t?.cicd.failed ?? 0)} failed${
              t?.cicd.active ? ` · ${fmt(t.cicd.active)} active` : ""
            }`,
          },
          {
            label: "Failure rate",
            value: `${failureRate.toFixed(failureRate > 0 && failureRate < 10 ? 1 : 0)}%`,
            hint: `${fmt(failed)} failed of ${fmt(finished)} finished`,
            tone: failed > 0 ? "critical" : "default",
          },
        ]}
      />
    </div>
  );
}
