"use client";

import { ChannelsSection } from "./channels-section";
import { DigestSection } from "./digest-section";
import { LiveAlertsSection } from "./live-alerts-section";

export function WebhooksTab({ projects }: { projects: { project_id: string; name: string }[] }) {
  return (
    <div className="space-y-8">
      <ChannelsSection projects={projects} />
      <DigestSection projects={projects} />
      <LiveAlertsSection />
    </div>
  );
}
