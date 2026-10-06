"use client";

import type { ComponentProps, ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Icon-only button whose name shows on hover. The trigger is a wrapping span so the tooltip
// still explains *why* when the button is disabled (disabled buttons swallow pointer events).
export function IconAction({
  label,
  children,
  variant = "ghost",
  size = "icon-sm",
  ...props
}: { label: string; children: ReactNode } & Omit<ComponentProps<typeof Button>, "aria-label">) {
  return (
    <Tooltip>
      <TooltipTrigger render={<span className="inline-flex" />}>
        <Button variant={variant} size={size} aria-label={label} {...props}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

// "⋯" menu for a row's secondary actions. Children are DropdownMenuItem / DropdownMenuSeparator.
export function RowActionsMenu({ label = "More actions", children }: { label?: string; children: ReactNode }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={label} />}>
        <MoreHorizontal />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-auto min-w-44">
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
