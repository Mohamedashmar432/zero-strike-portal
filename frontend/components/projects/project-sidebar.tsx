"use client";

import {
  Activity,
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
import { cn } from "@/lib/utils";
import type { Project, ProjectScanActivity } from "@/lib/api/projects";

/**
 * A group is now purely a visual cluster — a hairline and some space between related items,
 * no heading. The headings ("SECURITY ENGINES", "AI & AUTOMATION", …) shouted four labels at
 * a rail of eleven items, which is more chrome than the items themselves. The grouping still
 * carries the meaning; it just does it with spacing instead of words.
 */
export interface ProjectSidebarCategory {
  /** Not rendered — kept as the React key and as a note on what the cluster is. */
  title: string;
  items: {
    id: string;
    label: string;
    icon: typeof LayoutDashboard;
    badge?: string | number;
    isPreview?: boolean;
    /** Unreleased — omitted from the rail but the tab still exists. */
    hidden?: boolean;
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
        // DAST and Attack Simulation are unreleased — no scan engine exists
        // server-side yet. Hidden rather than deleted: drop `hidden` to bring
        // them back once the engines ship. The tab components and their
        // PreviewNotice markers are untouched.
        { id: "dast", label: "DAST Endpoints", icon: Activity, isPreview: true, hidden: true },
        { id: "attack-sim", label: "Attack Simulation", icon: Swords, isPreview: true, hidden: true },
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
    <aside className="flex w-56 shrink-0 flex-col rounded-lg border border-border bg-card py-2.5">
      {/* Overview Primary Button */}
      <button
        type="button"
        onClick={() => onTabChange("overview")}
        className={cn(
          "relative mb-3 flex w-full cursor-pointer items-center justify-between px-3.5 py-2 text-left font-mono text-[13px] tracking-[-0.01em] transition-colors duration-150",
          isOverview
            ? "bg-accent font-semibold text-foreground"
            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
        )}
      >
        {isOverview && <span className="absolute inset-y-0 left-0 w-[3px] bg-signal" />}
        <div className="flex items-center gap-2.5">
          <LayoutDashboard
            className={cn("size-4", isOverview ? "text-signal" : "text-muted-foreground")}
          />
          <span>Project Overview</span>
        </div>
        {isOverview && <ChevronRight className="size-3.5 text-muted-foreground" />}
      </button>

      {/* Navigation. Clusters separated by a hairline, not by a heading. */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden">
        {categories.map((cat, i) => (
          <div
            key={cat.title}
            className={cn(
              "py-1.5",
              i > 0 && "mt-1.5 border-t border-border/60"
            )}
          >
            <div className="space-y-0.5">
              {cat.items.filter((item) => !item.hidden).map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onTabChange(item.id)}
                    className={cn(
                      "group relative flex w-full cursor-pointer items-center justify-between py-1.5 pl-3.5 pr-2.5 text-left font-mono text-[12px] tracking-[-0.01em] transition-colors duration-150",
                      isActive
                        ? "bg-accent font-semibold text-foreground"
                        : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
                    )}
                  >
                    {isActive && <span className="absolute inset-y-0 left-0 w-[3px] bg-signal" />}
                    <div className="flex items-center gap-2.5 min-w-0">
                      <Icon
                        className={cn(
                          "size-3.5 shrink-0 transition-colors",
                          isActive ? "text-signal" : "text-muted-foreground group-hover:text-foreground"
                        )}
                      />
                      <span className="truncate">{item.label}</span>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {/* "NEW" reads as shipped; these tabs have no engine behind
                          them, so they are labelled as previews instead. */}
                      {item.isPreview && (
                        <span
                          title="Design preview — no scan engine connected"
                          className="rounded-sm border-l-2 border-severity-medium bg-severity-medium-tint px-1 font-mono text-[9px] font-bold text-severity-medium"
                        >
                          PREVIEW
                        </span>
                      )}
                      {item.badge !== undefined && item.badge !== 0 && (
                        <span
                          className={cn(
                            "rounded-sm px-1.5 font-mono text-[10px] font-semibold tabular-nums",
                            isActive
                              ? "bg-signal/20 text-signal"
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
