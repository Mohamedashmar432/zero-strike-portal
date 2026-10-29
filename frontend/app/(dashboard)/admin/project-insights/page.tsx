import { redirect } from "next/navigation";

// Project Insights became the Control Panel's Projects and Requests tabs.
export default function ProjectInsightsRedirect() {
  redirect("/admin/control-panel");
}
