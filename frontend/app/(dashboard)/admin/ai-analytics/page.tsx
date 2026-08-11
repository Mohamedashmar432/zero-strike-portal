"use client";

import { AiAnalyticsDashboard } from "@/components/ai/ai-analytics-dashboard";
import { PageHeader } from "@/components/layout/page-header";

export default function AdminAiAnalyticsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Analytics"
        description="LLM spend, tokens, latency and failures across every project in the portal."
      />
      {/* Same component the project tab renders — portal scope just widens the query and adds
          the per-project breakdown. */}
      <AiAnalyticsDashboard scope="portal" />
    </div>
  );
}
