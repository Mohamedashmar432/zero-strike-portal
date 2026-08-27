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
 * The mark is a slashed zero inside registration ticks.
 *
 * Why: `0` struck through by a diagonal is the exact glyph feature this app
 * turns on in JetBrains Mono (`ss01`/`zero`, see globals.css) so that O and 0
 * never get confused in a hash, a CVE id or a commit sha. So the logo isn't a
 * metaphor bolted on afterwards — it's the product's own typography, drawn
 * large. "Zero" (the aperture) "Strike" (the slash).
 *
 * Deliberately two flat colors: currentColor for the chrome, --signal for the
 * strike. No gradients, no glow filter — a gradient-stacked mark is the single
 * loudest "generated asset" tell, and the old one used emerald/cyan/violet that
 * appeared nowhere else in the UI.
 */
export function ZeroStrikeLogoIcon({ className }: { className?: string }) {
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

      {/* The zero: an aperture, not a shield. */}
      <circle cx="12" cy="12" r="5.6" stroke="currentColor" strokeWidth="2.1" />

      {/* The strike. Overshoots the aperture on both ends the way a real slashed
          zero does, and sits on the signal accent so it's the one saturated
          pixel in the chrome. */}
      <path
        d="M7.4 16.6 16.6 7.4"
        stroke="var(--signal)"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function ZeroStrikeLogo({
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
        <ZeroStrikeLogoIcon />
      </div>

      {showText && (
        <div className="flex min-w-0 flex-col gap-0.5">
          {/* One face, one color, tight tracking. The old wordmark switched font
              family mid-word and tinted half of it — two tells at once. */}
          <span
            className={cn(
              "font-mono font-bold leading-none tracking-[-0.04em] text-foreground",
              currentSize.text
            )}
          >
            ZeroStrike
          </span>
          <span className={cn("legend text-muted-foreground", currentSize.sub)}>
            <span className="text-signal">{"//"}</span> SAST Control
          </span>
        </div>
      )}
    </div>
  );
}
