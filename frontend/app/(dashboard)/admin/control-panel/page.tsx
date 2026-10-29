"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ActivityTab } from "@/components/control-panel/activity-tab";
import { DateRangeBar, useDateRange } from "@/components/control-panel/date-range";
import { OverviewTab } from "@/components/control-panel/overview-tab";
import { ProjectsTab } from "@/components/control-panel/projects-tab";
import { RequestsTable } from "@/components/control-panel/requests-table";
import { WebhooksTab } from "@/components/control-panel/webhooks-tab";
import { PageHeader } from "@/components/layout/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getProjectInsights } from "@/lib/api/project-insights";
import { queryKeys } from "@/lib/api/query-keys";

const TABS = [
  { value: "overview", label: "Overview" },
  { value: "projects", label: "Projects" },
  { value: "activity", label: "Project activity" },
  { value: "requests", label: "Requests & errors" },
  { value: "webhooks", label: "Webhooks & alerts" },
] as const;
type TabValue = (typeof TABS)[number]["value"];
const isTab = (v: string | null): v is TabValue => TABS.some((t) => t.value === v);

function ControlPanel() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab: TabValue = isTab(params.get("tab")) ? (params.get("tab") as TabValue) : "overview";
  const projectParam = params.get("project");

  const dates = useDateRange();
  const { range } = dates;

  const go = (next: { tab: TabValue; project?: string | null }) => {
    const q = new URLSearchParams();
    q.set("tab", next.tab);
    if (next.tab === "activity" && next.project) q.set("project", next.project);
    router.replace(`${pathname}?${q}`, { scroll: false });
  };

  const insights = useQuery({
    queryKey: queryKeys.admin.projectInsights(range?.since ?? "", range?.until ?? ""),
    queryFn: () => getProjectInsights(range!),
    enabled: range !== null,
    placeholderData: keepPreviousData,
  });
  const projects = insights.data?.projects ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Administration / Control Panel"
        title="Control Panel"
        description="Who is using the portal, what every project is doing, what failed and why, and where alerts and the digest are sent."
      />

      <DateRangeBar state={dates} />

      <Tabs value={tab} onValueChange={(v) => isTab(v as string) && go({ tab: v as TabValue, project: projectParam })}>
        <TabsList variant="line" className="h-9 flex-wrap">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview" className="pt-4">
          <OverviewTab data={insights.data} isLoading={insights.isLoading} />
        </TabsContent>
        <TabsContent value="projects" className="pt-4">
          <ProjectsTab
            data={insights.data}
            isLoading={insights.isLoading}
            isError={insights.isError}
            onOpenActivity={(id) => go({ tab: "activity", project: id })}
          />
        </TabsContent>
        <TabsContent value="activity" className="pt-4">
          <ActivityTab
            range={range}
            projectId={projectParam}
            projects={projects}
            onProjectChange={(id) => go({ tab: "activity", project: id })}
          />
        </TabsContent>
        <TabsContent value="requests" className="pt-4">
          <RequestsTable range={range} projects={projects} />
        </TabsContent>
        <TabsContent value="webhooks" className="pt-4">
          <WebhooksTab projects={projects} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function ControlPanelPage() {
  return (
    <Suspense fallback={null}>
      <ControlPanel />
    </Suspense>
  );
}
