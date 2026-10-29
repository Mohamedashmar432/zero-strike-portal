"use client";

import { cn } from "@/lib/utils";

/**
 * Multi-select over projects where an empty selection means "all projects" — the same rule the
 * webhook routing and the digest use, so the control says it out loud instead of implying "none".
 */
export function ProjectPicker({
  projects,
  value,
  onChange,
  className,
}: {
  projects: { project_id: string; name: string }[];
  value: string[];
  onChange: (ids: string[]) => void;
  className?: string;
}) {
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
  return (
    <div className={cn("space-y-1.5", className)}>
      <label className="flex items-center gap-2 text-sm">
        <input type="radio" className="size-4" checked={value.length === 0} onChange={() => onChange([])} />
        All projects
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="radio"
          className="size-4"
          checked={value.length > 0}
          onChange={() => value.length === 0 && projects[0] && onChange([projects[0].project_id])}
        />
        Only selected projects{value.length > 0 ? ` (${value.length})` : ""}
      </label>
      {value.length > 0 && (
        <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-border p-2">
          {projects.map((p) => (
            <label key={p.project_id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={value.includes(p.project_id)}
                onChange={() => toggle(p.project_id)}
              />
              {p.name}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
