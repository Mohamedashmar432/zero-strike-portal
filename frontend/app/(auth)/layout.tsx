import { ZeroStrikeLogo } from "@/components/brand/logo";

/**
 * Auth shell. Left-aligned brand over a single panel on the dot-grid canvas,
 * with registration ticks in the viewport corners — the same instrument framing
 * as the logo mark, at page scale. Centering the logo above a centered card is
 * the default every generated login page lands on; the asymmetry plus the
 * corner marks is the whole difference.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-canvas relative flex min-h-screen items-center justify-center px-5 py-12">
      {/* Viewport registration ticks. Decorative only. */}
      <div className="pointer-events-none absolute inset-4 hidden sm:block" aria-hidden="true">
        <span className="absolute left-0 top-0 size-4 border-l border-t border-hairline" />
        <span className="absolute right-0 top-0 size-4 border-r border-t border-hairline" />
        <span className="absolute bottom-0 left-0 size-4 border-b border-l border-hairline" />
        <span className="absolute bottom-0 right-0 size-4 border-b border-r border-hairline" />
      </div>

      {/* The panel is the thing the eye anchors on, so the PANEL gets the
          vertical centre line — not the panel-plus-brand block. With the brand
          inside the centred box it added its own height to the column and
          pushed the form ~32px below centre, which reads as "sitting low".
          Above 560px tall the brand is lifted out of the flow; on shorter
          viewports it drops back into the column so it can never clip. */}
      <div className="relative w-full max-w-sm">
        <div className="mb-5 [@media(min-height:560px)]:absolute [@media(min-height:560px)]:bottom-full [@media(min-height:560px)]:left-0">
          <ZeroStrikeLogo size="lg" animated />
        </div>
        {children}
      </div>
    </div>
  );
}
