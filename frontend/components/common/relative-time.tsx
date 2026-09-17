"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatRelativeTime, parseApiDate } from "@/lib/utils";

/**
 * Relative timestamp ("2 days ago") with the exact timestamp on hover -- the work queue's
 * First/Last seen columns need both: relative for scanning a list at a glance, exact for
 * anyone who needs to know precisely when.
 */
export function RelativeTime({ iso, className }: { iso: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger render={<span className={className} tabIndex={0} />}>
        {formatRelativeTime(iso)}
      </TooltipTrigger>
      <TooltipContent>{parseApiDate(iso).toLocaleString()}</TooltipContent>
    </Tooltip>
  );
}
