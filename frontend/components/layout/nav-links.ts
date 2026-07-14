import {
  Bell,
  FileText,
  FolderKanban,
  LayoutDashboard,
  Plug,
  ScrollText,
  Settings,
  Sparkles,
  User,
  Users,
  Wand2,
} from "lucide-react";

export const mainLinks = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/projects", label: "Projects", icon: FolderKanban },
];

export const adminLinks = [
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/audit-log", label: "Audit Log", icon: ScrollText },
];

export const settingsLinks = [
  { href: "/settings/profile", label: "Profile", icon: User },
  { href: "/settings/integrations", label: "Integrations", icon: Plug },
  { href: "/settings/general", label: "General", icon: Settings },
  { href: "/settings/ai-provider", label: "AI Provider", icon: Sparkles },
  { href: "/settings/auto-fix", label: "Auto-fix", icon: Wand2 },
  { href: "/settings/notifications", label: "Notifications", icon: Bell },
  { href: "/settings/report-templates", label: "Report Templates", icon: FileText },
];
