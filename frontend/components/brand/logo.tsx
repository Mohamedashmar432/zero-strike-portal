import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  showText?: boolean;
  animated?: boolean;
}

const sizeMap = {
  xs: { box: "size-5", text: "text-[11px]", sub: "text-[7px]" },
  sm: { box: "size-7", text: "text-sm", sub: "text-[8px]" },
  md: { box: "size-9", text: "text-lg", sub: "text-[9px]" },
  lg: { box: "size-11", text: "text-2xl", sub: "text-[10px]" },
  xl: { box: "size-14", text: "text-3xl", sub: "text-xs" },
};

/**
 * The mark is a shield crossed by a scan line, inside registration ticks.
 *
 * Why: the shield is the name; the line is what the product actually does — a
 * scanner sweeping the code it protects. It overshoots the shield on both
 * sides so it reads as a pass *across* the thing, not a stripe painted on it.
 *
 * Deliberately two flat colors: currentColor for the chrome, --signal for the
 * scan line. No gradients, no glow filter — a gradient-stacked mark is the
 * single loudest "generated asset" tell.
 */
export function ThinkShieldLogoIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("size-full shrink-0 select-none", className)}
      aria-hidden="true"
    >
      {/* Registration ticks — the instrument frame. Corners only, so the mark
          reads as "aligned in a viewport" rather than boxed in. */}
      <g stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity="0.4">
        <path d="M1.5 5.5V2.75A1.25 1.25 0 0 1 2.75 1.5H5.5" />
        <path d="M18.5 1.5h2.75A1.25 1.25 0 0 1 22.5 2.75V5.5" />
        <path d="M22.5 18.5v2.75a1.25 1.25 0 0 1-1.25 1.25H18.5" />
        <path d="M5.5 22.5H2.75A1.25 1.25 0 0 1 1.5 21.25V18.5" />
      </g>

      {/* The shield. */}
      <path
        d="M12 4.3 17.9 6.5v4.9c0 3.9-2.5 6.9-5.9 8.4-3.4-1.5-5.9-4.5-5.9-8.4V6.5Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />

      {/* The scan line — the one saturated pixel in the chrome. */}
      <path d="M4.6 11.4h14.8" stroke="var(--signal)" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

/** Brand rule: lowercase "think", bold; "Shield" regular. */
export function ThinkShieldWordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-mono leading-none tracking-[-0.04em]", className)}>
      <span className="font-bold">think</span>
      <span className="font-normal">Shield</span>
    </span>
  );
}

export function ThinkShieldLogo({
  className,
  size = "sm",
  showText = true,
  animated = false,
}: LogoProps) {
  const currentSize = sizeMap[size];

  return (
    <div className={cn("inline-flex items-center gap-2.5 select-none", className)}>
      <div
        className={cn(
          "flex shrink-0 items-center justify-center text-foreground transition-colors duration-200",
          currentSize.box,
          animated && "hover:text-signal"
        )}
      >
        <ThinkShieldLogoIcon />
      </div>

      {showText && (
        <div className="flex min-w-0 flex-col gap-0.5">
          <ThinkShieldWordmark className={cn("text-foreground", currentSize.text)} />
          <span className={cn("legend text-muted-foreground", currentSize.sub)}>
            <span className="text-signal">{"//"}</span> Security Control
          </span>
        </div>
      )}
    </div>
  );
}
