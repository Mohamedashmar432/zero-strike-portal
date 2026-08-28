"use client";

import {
  Bell,
  CheckCircle2,
  FileCheck,
  Globe,
  Lock,
  Save,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sliders,
  Sparkles,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { listFrameworks } from "@/lib/api/compliance";
import { queryKeys } from "@/lib/api/query-keys";

interface ProjectComplianceConfigTabProps {
  projectId: string;
}

export function ProjectComplianceConfigTab({ projectId }: ProjectComplianceConfigTabProps) {
  // Driven by the real catalog endpoint rather than a hardcoded list. That endpoint returns only
  // the frameworks the evaluator will actually run (SOC 2 and ISO 27001 today), so this tab can
  // never advertise a framework an audit would refuse.
  const { data: catalog, isLoading } = useQuery({
    queryKey: queryKeys.compliance.frameworks(),
    queryFn: listFrameworks,
  });
  const frameworks = catalog?.items ?? [];

  const [slackAlerts, setSlackAlerts] = useState(true);
  const [emailDigest, setEmailDigest] = useState(true);
  const [autoRemediate, setAutoRemediate] = useState(false);
  const [retentionDays, setRetentionDays] = useState("365");

  function handleSave() {
    // Was a success toast for a save that never happened. Nothing on this tab is persisted yet,
    // and a UI that reports success for a no-op is worse than one that admits the gap.
    toast.info(
      "These policy settings aren't stored yet. Framework selection, scope and AI depth are " +
        "chosen per audit in Compliance → Run audit."
    );
  }

  return (
    <div className="space-y-6">
      {/* Header Info */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/60 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <Sliders className="size-5 text-muted-foreground" />
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              Compliance Governance & Policy Configuration
            </h2>
            <Badge variant="outline" className="font-mono text-[10px]">
              Project Level
            </Badge>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            The frameworks this project can be assessed against, plus the automation policies
            planned for them. The policy switches below are not stored yet — audits are configured
            per run in Compliance → Run audit.
          </p>
        </div>

        <Button
          onClick={handleSave}
          size="sm"
          variant="outline"
          className="gap-1.5 font-medium shrink-0"
        >
          <Save className="size-3.5" />
          <span>Save Changes</span>
        </Button>
      </div>

      {/* Target Frameworks Grid */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
          Supported Compliance Frameworks ({frameworks.length})
        </h3>
        <p className="text-xs text-muted-foreground">
          These are the frameworks whose control-to-evidence mapping has been reviewed control by
          control. Others are not offered rather than offered with mappings nobody has checked. Pick
          which to assess when you run an audit.
        </p>

        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
          {isLoading && <Skeleton className="h-32 w-full" />}
          {frameworks.map((framework) => {
            const manualOnly = framework.controls_total - framework.assessed_total;
            return (
              <Card key={framework.key} className="border-primary/40 bg-card/90 transition-all">
                <CardHeader className="p-4 pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1 min-w-0">
                      <CardTitle className="text-sm font-semibold text-foreground">
                        {framework.title}
                      </CardTitle>
                      <p className="text-[11px] font-mono text-muted-foreground">
                        {framework.controls_total} controls · {framework.assessed_total} assessable
                        from code · {manualOnly} manual review
                      </p>
                    </div>
                    <Badge variant="secondary" className="shrink-0 font-mono text-[10px]">
                      Supported
                    </Badge>
                  </div>
                </CardHeader>

                <CardContent className="p-4 pt-2">
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {framework.scope_note}
                  </p>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Audit Automation & Notification Policies */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Audit Triggers */}
        <Card className="border-border/80 bg-card/60">
          <CardHeader className="p-4 pb-3 border-b border-border/60">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono flex items-center gap-2">
              <ShieldCheck className="size-4 text-muted-foreground" />
              Automated Audit Policies
              <Badge variant="outline" className="font-mono text-[10px] normal-case">
                Not stored yet
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 space-y-4 text-xs">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="font-medium text-foreground">Continuous Posture Evaluation</Label>
                <p className="text-[11px] text-muted-foreground">
                  Trigger compliance control assessment on every completed SAST scan. Not
                  implemented — audits are started by hand from the Compliance tab.
                </p>
              </div>
              <Switch checked={false} disabled />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="font-medium text-foreground">Auto-Generate Remediation Drafts</Label>
                <p className="text-[11px] text-muted-foreground">
                  Invoke AI Agent to draft PRs when controls fail.
                </p>
              </div>
              <Switch checked={autoRemediate} onCheckedChange={setAutoRemediate} />
            </div>

            <div className="space-y-1.5 pt-2 border-t border-border/40">
              <Label className="font-medium text-foreground">Audit Evidence Retention (Days)</Label>
              <Input
                type="number"
                value={retentionDays}
                onChange={(e) => setRetentionDays(e.target.value)}
                className="font-mono text-xs max-w-32 h-8"
              />
            </div>
          </CardContent>
        </Card>

        {/* Notifications */}
        <Card className="border-border/80 bg-card/60">
          <CardHeader className="p-4 pb-3 border-b border-border/60">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono flex items-center gap-2">
              <Bell className="size-4 text-muted-foreground" />
              Drift & Violation Alerts
              <Badge variant="outline" className="font-mono text-[10px] normal-case">
                Not stored yet
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 space-y-4 text-xs">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="font-medium text-foreground">Slack / Teams Webhook Alerts</Label>
                <p className="text-[11px] text-muted-foreground">
                  Notify incident channels when high-severity controls fail.
                </p>
              </div>
              <Switch checked={slackAlerts} onCheckedChange={setSlackAlerts} />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="font-medium text-foreground">Weekly Executive Digest</Label>
                <p className="text-[11px] text-muted-foreground">
                  Send PDF compliance report to project administrators.
                </p>
              </div>
              <Switch checked={emailDigest} onCheckedChange={setEmailDigest} />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
