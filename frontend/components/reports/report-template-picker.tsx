"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { reportTemplatePreviewUrl, type ReportTemplateId } from "@/lib/api/report-templates";

const TEMPLATES: { id: ReportTemplateId; label: string; description: string }[] = [
  { id: "standard", label: "Standard", description: "Plain, tabular PDF report." },
  {
    id: "executive",
    label: "Executive",
    description: "Branded cover page, risk banner, and OWASP compliance grid.",
  },
];

export type ReportTemplateValue = ReportTemplateId | "inherit";

// Two small preview windows (rendered from fixed sample data via the backend's preview
// endpoint) plus a select to change the active choice. Used both in Settings (workspace
// default, allowInherit=false) and a Project's Overview tab (allowInherit=true).
export function ReportTemplatePicker({
  value,
  onChange,
  allowInherit = false,
}: {
  value: ReportTemplateValue;
  onChange: (value: ReportTemplateValue) => void;
  allowInherit?: boolean;
}) {
  return (
    <div className="space-y-4">
      <Select value={value} onValueChange={(v) => v && onChange(v as ReportTemplateValue)}>
        <SelectTrigger size="sm" className="w-full sm:w-64">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {allowInherit && <SelectItem value="inherit">Inherit workspace default</SelectItem>}
          {TEMPLATES.map((t) => (
            <SelectItem key={t.id} value={t.id}>
              {t.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {TEMPLATES.map((t) => (
          <div key={t.id} className="space-y-2">
            <p className="text-sm font-medium">
              {t.label}
              {value === t.id ? " (selected)" : ""}
            </p>
            <p className="text-xs text-muted-foreground">{t.description}</p>
            <div className="h-64 w-full overflow-hidden rounded-lg border border-border bg-white">
              <iframe
                src={reportTemplatePreviewUrl(t.id)}
                title={`${t.label} report preview`}
                className="h-[600px] w-[250%] origin-top-left scale-[0.4]"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
