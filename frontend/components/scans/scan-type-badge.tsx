import { cva, type VariantProps } from "class-variance-authority";
import { Cloud, GitBranch, Terminal } from "lucide-react";
import { cn } from "@/lib/utils";

const scanTypeBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide",
  {
    variants: {
      scanType: {
        local: "bg-muted-foreground/15 text-muted-foreground",
        cloud: "bg-brand/15 text-brand",
        cicd: "bg-status-success/15 text-status-success",
      },
    },
    defaultVariants: { scanType: "local" },
  }
);

const icons = { local: Terminal, cloud: Cloud, cicd: GitBranch };
const labels = { local: "Local", cloud: "Cloud", cicd: "CI/CD" };

type ScanTypeBadgeProps = VariantProps<typeof scanTypeBadgeVariants> & {
  className?: string;
};

export function ScanTypeBadge({ scanType, className }: ScanTypeBadgeProps) {
  const type = scanType ?? "local";
  const Icon = icons[type];
  return (
    <span className={cn(scanTypeBadgeVariants({ scanType: type }), className)}>
      <Icon className="size-3" />
      {labels[type]}
    </span>
  );
}
