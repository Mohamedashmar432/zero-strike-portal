"use client";

import {
  AlertOctagon,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  CornerDownRight,
  Database,
  Flame,
  Globe,
  Key,
  Lock,
  Play,
  RefreshCw,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Swords,
  Terminal,
  UserCheck,
  XCircle,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PreviewNotice } from "@/components/common/preview-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ProjectAttackSimTabProps {
  projectId: string;
}

interface AttackScenario {
  id: string;
  name: string;
  category: string;
  mitreTechnique: string;
  severity: "critical" | "high" | "medium";
  description: string;
  status: "contained" | "vulnerable" | "simulated";
  steps: { title: string; node: string; status: "success" | "blocked" | "pending" }[];
}

const SCENARIOS: AttackScenario[] = [
  {
    id: "sim-ssrf-imdsv2",
    name: "SSRF to Cloud Metadata Exfiltration (IMDSv2)",
    category: "Cloud Infrastructure",
    mitreTechnique: "T1552.005",
    severity: "critical",
    description:
      "Emulates an adversary attempting to bypass SSRF filters via DNS rebinding to query the AWS/Azure Instance Metadata Service and steal IAM credentials.",
    status: "contained",
    steps: [
      { title: "Public Ingress / Webhook Payload", node: "POST /v1/webhooks", status: "success" },
      { title: "SSRF Filter Bypass (169.254.169.254)", node: "DNS Rebind Probe", status: "blocked" },
      { title: "IAM Role Token Extraction", node: "IMDSv2 Endpoint", status: "blocked" },
    ],
  },
  {
    id: "sim-bola-privesc",
    name: "BOLA IDOR to Organization Privilege Escalation",
    category: "API & Identity",
    mitreTechnique: "T1078.004",
    severity: "high",
    description:
      "Simulates user token manipulation on resource ID parameters to access unauthorized tenant objects and administrative billing controls.",
    status: "contained",
    steps: [
      { title: "User Auth Context (Tenant A)", node: "Bearer Token", status: "success" },
      { title: "Resource ID Tampering", node: "GET /api/orgs/tenant_b/members", status: "blocked" },
      { title: "Admin Role Injection", node: "PATCH /api/users/role", status: "blocked" },
    ],
  },
  {
    id: "sim-sqli-exfil",
    name: "Stacked SQL Injection to Database Exfiltration",
    category: "Data Store",
    mitreTechnique: "T1190",
    severity: "critical",
    description:
      "Injects parameterized evasion payloads into search query filters to verify database query parameterization and data isolation.",
    status: "contained",
    steps: [
      { title: "Vulnerable Search Parameter", node: "GET /v1/transactions?q='", status: "success" },
      { title: "Stacked Query Execution", node: "UNION SELECT ...", status: "blocked" },
      { title: "Data Dump Probe", node: "Users Table", status: "blocked" },
    ],
  },
];

export function ProjectAttackSimTab({ projectId }: ProjectAttackSimTabProps) {
  const [selectedScenario, setSelectedScenario] = useState<AttackScenario>(SCENARIOS[0]);
  const [isRunning, setIsRunning] = useState(false);

  function handleRunSimulation(scenario: AttackScenario) {
    setIsRunning(true);
    // Same reasoning as the DAST tab: no simulation engine exists, so no
    // containment result may be reported.
    toast.info(`Attack Simulation is a preview — "${scenario.name}" cannot be executed yet.`);
    setTimeout(() => setIsRunning(false), 600);
  }

  return (
    <div className="space-y-6">
      <PreviewNotice feature="Attack Simulation" />

      {/* Top Banner Overview */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/60 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <Swords className="size-5 text-severity-critical" />
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              Synthetic Attack Simulation & Threat Emulation
            </h2>
            <Badge variant="outline" className="font-mono text-[10px] text-severity-critical border-severity-critical/30">
              Adversary Suite
            </Badge>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Continuously validate detection & defense mechanisms by executing synthetic attack chains across your codebase and runtime endpoints.
          </p>
        </div>

        <Button
          onClick={() => handleRunSimulation(selectedScenario)}
          disabled
          title="No simulation engine is connected yet"
          size="sm"
          variant="outline"
          className="shrink-0 gap-1.5"
        >
          <Play className="size-3.5 fill-current" />
          <span>Run Selected Simulation</span>
        </Button>
      </div>

      {/* Scenario Grid & Attack Path Visualizer */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Scenario List (Left 5 Cols) */}
        <div className="lg:col-span-5 space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
            Available Threat Scenarios ({SCENARIOS.length})
          </h3>
          <div className="space-y-2">
            {SCENARIOS.map((scenario) => {
              const isSelected = selectedScenario.id === scenario.id;
              return (
                <Card
                  key={scenario.id}
                  onClick={() => setSelectedScenario(scenario)}
                  className={`cursor-pointer transition-all border-border/80 bg-card/60 hover:border-border hover:bg-card/90 ${
                    isSelected ? "border-severity-critical/50 bg-severity-critical/10" : ""
                  }`}
                >
                  <CardContent className="p-3.5 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="font-semibold text-xs text-foreground leading-snug">
                        {scenario.name}
                      </h4>
                      <Badge
                        variant="secondary"
                        className="font-mono text-[10px] uppercase text-status-success shrink-0"
                      >
                        Contained
                      </Badge>
                    </div>
                    <p className="text-[11px] text-muted-foreground line-clamp-2">
                      {scenario.description}
                    </p>
                    <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground pt-1 border-t border-border/40">
                      <span>MITRE: {scenario.mitreTechnique}</span>
                      <span className="capitalize">{scenario.category}</span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>

        {/* Attack Path Visualizer & Containment Map (Right 7 Cols) */}
        <div className="lg:col-span-7 space-y-4">
          <Card className="border-border/80 bg-card/60">
            <CardHeader className="border-b border-border/60 pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
                  Attack Path & Blast Radius Visualizer
                </CardTitle>
                <Badge variant="outline" className="font-mono text-[10px] text-severity-critical">
                  {selectedScenario.mitreTechnique}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="p-4 space-y-5">
              <div>
                <h4 className="font-bold text-sm text-foreground">{selectedScenario.name}</h4>
                <p className="text-xs text-muted-foreground mt-1">
                  {selectedScenario.description}
                </p>
              </div>

              {/* Step Flow Nodes */}
              <div className="space-y-3 border-l-2 border-border/80 pl-4 ml-2">
                {selectedScenario.steps.map((step, idx) => (
                  <div key={idx} className="relative space-y-1">
                    <div className="flex items-center gap-2">
                      {step.status === "blocked" ? (
                        <div className="flex size-5 items-center justify-center rounded-full bg-status-success/20 text-status-success">
                          <ShieldCheck className="size-3" />
                        </div>
                      ) : (
                        <div className="flex size-5 items-center justify-center rounded-full bg-severity-critical/20 text-severity-critical">
                          <Flame className="size-3" />
                        </div>
                      )}
                      <span className="font-semibold text-xs text-foreground">
                        Step {idx + 1}: {step.title}
                      </span>
                      {step.status === "blocked" && (
                        <Badge variant="secondary" className="text-[10px] text-status-success font-mono">
                          BLOCKED BY POLICY
                        </Badge>
                      )}
                    </div>
                    <p className="font-mono text-[11px] text-muted-foreground pl-7">
                      Node: <span className="text-foreground">{step.node}</span>
                    </p>
                  </div>
                ))}
              </div>

              <div className="rounded-lg border border-border/60 bg-muted/30 p-3 flex items-center justify-between text-xs">
                <div className="space-y-0.5">
                  <span className="font-semibold text-foreground">Breach Containment Verification</span>
                  <p className="text-[11px] text-muted-foreground">
                    ZeroStrike SAST + Runtime policy prevented lateral movement.
                  </p>
                </div>
                <Button
                  size="xs"
                  onClick={() => handleRunSimulation(selectedScenario)}
                  className="gap-1 bg-severity-critical hover:bg-severity-critical/85 text-white font-medium"
                >
                  <Play className="size-3 fill-current" />
                  <span>Execute Vector</span>
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
