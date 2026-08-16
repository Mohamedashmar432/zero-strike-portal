"use client";

import {
  Activity,
  AlertOctagon,
  CheckCircle2,
  ChevronRight,
  Code2,
  FolderGit2,
  History,
  Key,
  LayoutDashboard,
  Radar,
  Settings,
  ShieldCheck,
  Sparkles,
  Swords,
  Users,
  Wand2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Project, ProjectScanActivity } from "@/lib/api/projects";

export interface ProjectSidebarCategory {
  title: string;
  items: {
    id: string;
    label: string;
    icon: typeof LayoutDashboard;
    badge?: string | number;
    isNew?: boolean;
  }[];
}

interface ProjectSidebarProps {
  project: Project;
  activity?: ProjectScanActivity;
  activeTab: string;
  onTabChange: (tabId: string) => void;
  counts?: {
    scans?: number;
    repos?: number;
    autoFixProposals?: number;
    members?: number;
  };
}

export function ProjectSidebar({
  activeTab,
  onTabChange,
  counts,
}: ProjectSidebarProps) {
  const isOverview = activeTab === "overview";

  const categories: ProjectSidebarCategory[] = [
    {
      title: "SECURITY ENGINES",
      items: [
        { id: "scans", label: "SAST Code Scanner", icon: Code2, badge: counts?.scans },
        { id: "dast", label: "DAST Live Endpoints", icon: Activity, isNew: true },
        { id: "attack-sim", label: "Attack Simulation", icon: Swords, isNew: true },
        { id: "history", label: "Scan History", icon: History },
      ],
    },
    {
      title: "AI & AUTOMATION",
      items: [
        { id: "auto-fix", label: "AI Auto-Fix", icon: Wand2, badge: counts?.autoFixProposals },
        { id: "ai-usage", label: "AI Auditor & Tokens", icon: Sparkles },
      ],
    },
    {
      title: "GOVERNANCE & AUDITS",
      items: [
        { id: "compliance", label: "Compliance Audits", icon: ShieldCheck },
        { id: "owasp", label: "OWASP Top 10", icon: Radar },
      ],
    },
    {
      title: "SETTINGS & CONFIG",
      items: [
        { id: "compliance-config", label: "Compliance Config", icon: Settings },
        { id: "repos", label: "Repositories", icon: FolderGit2, badge: counts?.repos },
        { id: "members", label: "Members & Access", icon: Users, badge: counts?.members },
        { id: "keys", label: "Project Tokens", icon: Key },
        { id: "settings", label: "Project Settings", icon: Settings },
      ],
    },
  ];

  return (
    <aside className="flex w-56 shrink-0 flex-col rounded-xl border border-border/80 bg-card/60 p-2.5 shadow-xs">
      {/* Overview Primary Button */}
      <button
        type="button"
        onClick={() => onTabChange("overview")}
        className={cn(
          "flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-xs font-semibold transition-all duration-150 text-left mb-3",
          isOverview
            ? "bg-primary text-primary-foreground shadow-sm"
            : "text-foreground/80 hover:bg-muted/50 hover:text-foreground"
        )}
      >
        <div className="flex items-center gap-2">
          <LayoutDashboard className={cn("size-4", isOverview ? "text-primary-foreground" : "text-primary")} />
          <span>Project Overview</span>
        </div>
        {isOverview && <ChevronRight className="size-3.5 opacity-80" />}
      </button>

      {/* Categorized Navigation Tree */}
      <nav className="flex-1 space-y-3.5 overflow-y-auto">
        {categories.map((cat) => (
          <div key={cat.title} className="space-y-1">
            <h3 className="px-2 text-[10px] font-bold tracking-wider text-muted-foreground/80 uppercase font-mono">
              {cat.title}
            </h3>
            <div className="space-y-0.5">
              {cat.items.map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onTabChange(item.id)}
                    className={cn(
                      "group flex w-full items-center justify-between rounded-lg py-1.5 text-xs font-medium transition-all duration-150 text-left",
                      isActive
                        ? "bg-primary/15 font-semibold text-primary shadow-xs border-l-2 border-primary pl-2 pr-2.5"
                        : "text-muted-foreground hover:bg-muted/40 hover:text-foreground pl-2.5 pr-2.5"
                    )}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon
                        className={cn(
                          "size-3.5 shrink-0 transition-colors",
                          isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
                        )}
                      />
                      <span className="truncate">{item.label}</span>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {item.isNew && (
                        <span className="rounded bg-sky-500/15 px-1 py-0.2 font-mono text-[9px] font-bold text-sky-400">
                          NEW
                        </span>
                      )}
                      {item.badge !== undefined && item.badge !== 0 && (
                        <span
                          className={cn(
                            "rounded-full px-1.5 py-0.2 font-mono text-[10px] font-semibold",
                            isActive
                              ? "bg-primary/25 text-primary"
                              : "bg-muted-foreground/15 text-muted-foreground"
                          )}
                        >
                          {item.badge}
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}
