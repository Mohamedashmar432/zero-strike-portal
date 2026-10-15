import { cva, type VariantProps } from "class-variance-authority";
import { Cloud, GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";

const scanTypeBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide",
  {
    variants: {
      scanType: {
        cloud: "bg-brand/15 text-brand",
        cicd: "bg-type-cicd/15 text-type-cicd",
      },
    },
    defaultVariants: { scanType: "cicd" },
  }
);

const icons = { cloud: Cloud, cicd: GitBranch };
const labels = { cloud: "Cloud", cicd: "CI/CD" };

type ScanTypeBadgeProps = VariantProps<typeof scanTypeBadgeVariants> & {
  className?: string;
};

export function ScanTypeBadge({ scanType, className }: ScanTypeBadgeProps) {
  const type = scanType ?? "cicd";
  const Icon = icons[type];
  return (
    <span className={cn(scanTypeBadgeVariants({ scanType: type }), className)}>
      <Icon className="size-3" />
      {labels[type]}
    </span>
  );
}
