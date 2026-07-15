"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { getWorkspaceReportTemplate, updateWorkspaceReportTemplate } from "@/lib/api/report-templates";
import {
  ReportTemplatePicker,
  type ReportTemplateValue,
} from "@/components/reports/report-template-picker";
import { Skeleton } from "@/components/ui/skeleton";

export default function ReportTemplatesSettingsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings", "report-template"],
    queryFn: getWorkspaceReportTemplate,
  });

  const mutation = useMutation({
    mutationFn: (template: "standard" | "executive") => updateWorkspaceReportTemplate(template),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "report-template"] });
      toast.success("Default report template updated");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Failed to update default report template"),
  });

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Report Templates</h2>
        <p className="text-sm text-muted-foreground">
          Customize the layout and branding of generated PDF reports.
        </p>
      </div>
      {isLoading || !data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <ReportTemplatePicker
          value={data.default_report_template}
          onChange={(v) => mutation.mutate(v as "standard" | "executive")}
        />
      )}
    </div>
  );
}
