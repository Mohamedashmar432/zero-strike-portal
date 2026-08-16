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
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

interface ProjectComplianceConfigTabProps {
  projectId: string;
}

interface FrameworkConfig {
  id: string;
  name: string;
  category: string;
  version: string;
  description: string;
  enabled: boolean;
  autoAudit: boolean;
}

export function ProjectComplianceConfigTab({ projectId }: ProjectComplianceConfigTabProps) {
  const [frameworks, setFrameworks] = useState<FrameworkConfig[]>([
    {
      id: "soc2",
      name: "SOC 2 Type II",
      category: "Trust Services Criteria",
      version: "2023 Revision",
      description: "Security, Confidentiality, and Processing Integrity controls for cloud software systems.",
      enabled: true,
      autoAudit: true,
    },
    {
      id: "iso27001",
      name: "ISO/IEC 27001",
      category: "ISMS Global Standard",
      version: "2022 Revision",
      description: "Information Security Management System Annex A technical & organizational controls.",
      enabled: true,
      autoAudit: true,
    },
    {
      id: "hipaa",
      name: "HIPAA Security Rule",
      category: "Healthcare Compliance",
      version: "45 CFR Part 164",
      description: "Safeguards for electronic protected health information (ePHI) encryption and access audit.",
      enabled: false,
      autoAudit: false,
    },
    {
      id: "nist80053",
      name: "NIST SP 800-53",
      category: "Federal Security Standard",
      version: "Rev. 5",
      description: "Security and Privacy Controls for Information Systems and Organizations.",
      enabled: false,
      autoAudit: false,
    },
    {
      id: "pci_dss",
      name: "PCI-DSS",
      category: "Payment Card Security",
      version: "v4.0",
      description: "Protection of cardholder data and secure coding standards for transaction processing.",
      enabled: true,
      autoAudit: false,
    },
  ]);

  const [slackAlerts, setSlackAlerts] = useState(true);
  const [emailDigest, setEmailDigest] = useState(true);
  const [autoRemediate, setAutoRemediate] = useState(false);
  const [retentionDays, setRetentionDays] = useState("365");

  function toggleFramework(id: string) {
    setFrameworks((prev) =>
      prev.map((f) => (f.id === id ? { ...f, enabled: !f.enabled } : f))
    );
  }

  function toggleAutoAudit(id: string) {
    setFrameworks((prev) =>
      prev.map((f) => (f.id === id ? { ...f, autoAudit: !f.autoAudit } : f))
    );
  }

  function handleSave() {
    toast.success("Compliance configuration saved successfully");
  }

  return (
    <div className="space-y-6">
      {/* Header Info */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/60 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <Sliders className="size-5 text-primary" />
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              Compliance Governance & Policy Configuration
            </h2>
            <Badge variant="outline" className="font-mono text-[10px]">
              Project Level
            </Badge>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Configure target audit frameworks, automated evaluation schedules, and continuous compliance alert thresholds.
          </p>
        </div>

        <Button onClick={handleSave} size="sm" className="gap-1.5 font-medium shrink-0 shadow-xs">
          <Save className="size-3.5" />
          <span>Save Changes</span>
        </Button>
      </div>

      {/* Target Frameworks Grid */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
          Target Compliance Frameworks ({frameworks.filter((f) => f.enabled).length} Active)
        </h3>

        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
          {frameworks.map((framework) => (
            <Card
              key={framework.id}
              className={`border-border/80 bg-card/60 transition-all ${
                framework.enabled ? "border-primary/40 bg-card/90 shadow-xs" : "opacity-70"
              }`}
            >
              <CardHeader className="p-4 pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <CardTitle className="text-sm font-semibold text-foreground truncate">
                        {framework.name}
                      </CardTitle>
                      <Badge variant="secondary" className="font-mono text-[10px]">
                        {framework.version}
                      </Badge>
                    </div>
                    <p className="text-[11px] font-mono text-muted-foreground">{framework.category}</p>
                  </div>
                  <Switch
                    checked={framework.enabled}
                    onCheckedChange={() => toggleFramework(framework.id)}
                    aria-label={`Toggle ${framework.name}`}
                  />
                </div>
              </CardHeader>

              <CardContent className="p-4 pt-2 space-y-3">
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {framework.description}
                </p>

                {framework.enabled && (
                  <div className="flex items-center justify-between pt-2 border-t border-border/40 text-xs">
                    <span className="text-[11px] text-muted-foreground font-mono">
                      Auto-audit on merge
                    </span>
                    <Switch
                      checked={framework.autoAudit}
                      onCheckedChange={() => toggleAutoAudit(framework.id)}
                      aria-label="Toggle automated audit"
                    />
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      {/* Audit Automation & Notification Policies */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Audit Triggers */}
        <Card className="border-border/80 bg-card/60">
          <CardHeader className="p-4 pb-3 border-b border-border/60">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono flex items-center gap-2">
              <ShieldCheck className="size-4 text-emerald-400" />
              Automated Audit Policies
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 space-y-4 text-xs">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="font-medium text-foreground">Continuous Posture Evaluation</Label>
                <p className="text-[11px] text-muted-foreground">
                  Trigger compliance control assessment on every completed SAST scan.
                </p>
              </div>
              <Switch checked={true} disabled />
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
              <Bell className="size-4 text-primary" />
              Drift & Violation Alerts
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
