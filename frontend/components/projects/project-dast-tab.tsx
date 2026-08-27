"use client";

import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  ExternalLink,
  Globe,
  Lock,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Server,
  Shield,
  ShieldAlert,
  Sliders,
  Terminal,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PreviewNotice } from "@/components/common/preview-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface ProjectDastTabProps {
  projectId: string;
}

export function ProjectDastTab({ projectId }: ProjectDastTabProps) {
  const [targetUrl, setTargetUrl] = useState("https://api.zerostrike.io/v1");
  const [profile, setProfile] = useState("api_fuzzing");
  const [isScanning, setIsScanning] = useState(false);

  const mockRuns = [
    {
      id: "dast-8831",
      target: "https://api.zerostrike.io/v1",
      profile: "API Fuzzing & Injection",
      endpointsTested: 48,
      vulnerabilities: { high: 1, medium: 2, low: 4 },
      duration: "42s",
      timestamp: "45 minutes ago",
      status: "completed",
    },
    {
      id: "dast-8820",
      target: "https://staging.zerostrike.io/api",
      profile: "Passive Baseline",
      endpointsTested: 32,
      vulnerabilities: { high: 0, medium: 1, low: 3 },
      duration: "18s",
      timestamp: "6 hours ago",
      status: "completed",
    },
  ];

  function handleLaunchDast() {
    setIsScanning(true);
    // No DAST engine exists server-side, so this must not report a result.
    // Claiming "0 critical blockers" for a scan that never ran is the kind of
    // false assurance a security tool can never emit.
    toast.info("DAST is a preview — no scan engine is connected yet.");
    setTimeout(() => setIsScanning(false), 600);
  }

  return (
    <div className="space-y-6">
      <PreviewNotice feature="DAST Live Endpoints" />

      {/* Top Banner Overview */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/60 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="size-5 text-severity-low" />
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              Dynamic Application Security Testing (DAST)
            </h2>
            <Badge variant="outline" className="text-severity-medium border-severity-medium/40">
              Not connected
            </Badge>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Execute dynamic HTTP fuzzing, header analysis, BOLA/IDOR detection, and OWASP API Top 10 probes against live runtime targets.
          </p>
        </div>

        <Button
          onClick={handleLaunchDast}
          disabled
          title="No DAST engine is connected yet"
          size="sm"
          variant="outline"
          className="shrink-0 gap-1.5"
        >
          <Play className="size-3.5 fill-current" />
          <span>Launch DAST Scan</span>
        </Button>
      </div>

      {/* Target Configuration & Scan Settings */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="lg:col-span-8 space-y-4">
          <Card className="border-border/80 bg-card/60">
            <CardHeader className="border-b border-border/60 pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
                Target Endpoint & Specification
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-foreground">Target Base URL</Label>
                  <div className="relative">
                    <Globe className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={targetUrl}
                      onChange={(e) => setTargetUrl(e.target.value)}
                      className="pl-8 text-xs font-mono"
                      placeholder="https://api.domain.com/v1"
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-foreground">Scan Execution Profile</Label>
                  <Select value={profile} onValueChange={(v) => v && setProfile(v)}>
                    <SelectTrigger aria-label="Scan execution profile" className="text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="passive" className="text-xs">
                        Passive Baseline (Headers & SSL)
                      </SelectItem>
                      <SelectItem value="active_crawler" className="text-xs">
                        Active Crawler (Links & Forms)
                      </SelectItem>
                      <SelectItem value="api_fuzzing" className="text-xs">
                        API Fuzzing & SQLi/XSS Injections
                      </SelectItem>
                      <SelectItem value="bola_idor" className="text-xs">
                        BOLA / IDOR Auth Escalation Probes
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 pt-2 border-t border-border/60">
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-foreground">Authentication Header (Optional)</Label>
                  <div className="relative">
                    <Lock className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      type="password"
                      defaultValue="Bearer eyJhbGciOi..."
                      className="pl-8 text-xs font-mono"
                      placeholder="Bearer token or API Key"
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-foreground">OpenAPI / Swagger Spec</Label>
                  <div className="relative">
                    <Server className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      defaultValue="https://api.zerostrike.io/v1/openapi.json"
                      className="pl-8 text-xs font-mono"
                      placeholder="URL or Upload OpenAPI 3.0"
                    />
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* DAST Scan History Table */}
          <Card className="border-border/80 bg-card/60">
            <CardHeader className="border-b border-border/60 pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
                Recent DAST Executions
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/40 text-xs">
                    <TableHead className="py-2.5">Scan ID</TableHead>
                    <TableHead className="py-2.5">Target</TableHead>
                    <TableHead className="py-2.5">Profile</TableHead>
                    <TableHead className="py-2.5">Endpoints</TableHead>
                    <TableHead className="py-2.5">Findings</TableHead>
                    <TableHead className="py-2.5">Timestamp</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mockRuns.map((run) => (
                    <TableRow key={run.id} className="text-xs">
                      <TableCell className="font-mono font-semibold text-foreground">
                        {run.id}
                      </TableCell>
                      <TableCell className="font-mono text-[11px] text-muted-foreground truncate max-w-[140px]">
                        {run.target}
                      </TableCell>
                      <TableCell className="text-xs font-medium">
                        {run.profile}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-foreground">
                        {run.endpointsTested} tested
                      </TableCell>
                      <TableCell>
                        <span className="font-mono text-[11px]">
                          <span className="font-bold text-severity-high">{run.vulnerabilities.high}H</span>{" "}
                          <span className="text-severity-medium">{run.vulnerabilities.medium}M</span>{" "}
                          <span className="text-severity-low">{run.vulnerabilities.low}L</span>
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-[11px] text-muted-foreground">
                        {run.timestamp}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>

        {/* DAST Capabilities & Security Safeguards Sidebar */}
        <div className="lg:col-span-4 space-y-4">
          <Card className="border-border/80 bg-card/60">
            <CardHeader className="border-b border-border/60 pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
                Active Test Vectors
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 space-y-3 text-xs">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-3.5 text-status-success shrink-0" />
                <span className="text-foreground font-medium">SQL & NoSQL Injection Payloads</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-3.5 text-status-success shrink-0" />
                <span className="text-foreground font-medium">Cross-Site Scripting (Reflected / Stored XSS)</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-3.5 text-status-success shrink-0" />
                <span className="text-foreground font-medium">Broken Object Level Auth (BOLA) IDOR</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-3.5 text-status-success shrink-0" />
                <span className="text-foreground font-medium">Server-Side Request Forgery (SSRF) Probes</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-3.5 text-status-success shrink-0" />
                <span className="text-foreground font-medium">CORS & Security Header Misconfigurations</span>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/80 bg-card/60">
            <CardHeader className="border-b border-border/60 pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
                Execution Safety Bounds
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 space-y-2 text-xs text-muted-foreground">
              <p>
                • Rate-limited to max <strong>30 req/sec</strong> to prevent backend denial-of-service.
              </p>
              <p>
                • Destructive HTTP methods (<code className="text-primary">DELETE</code>, <code className="text-primary">DROP</code>) are non-destructive simulated by default.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
