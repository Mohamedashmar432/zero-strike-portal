"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  showText?: boolean;
  animated?: boolean;
}

const sizeMap = {
  xs: { box: "size-6", text: "text-xs", sub: "text-[8px]" },
  sm: { box: "size-8", text: "text-sm", sub: "text-[9px]" },
  md: { box: "size-10", text: "text-base", sub: "text-[10px]" },
  lg: { box: "size-12", text: "text-lg", sub: "text-xs" },
  xl: { box: "size-16", text: "text-2xl", sub: "text-sm" },
};

/**
 * DevSecOps Custom Brand Logo for ZeroStrike
 * Combines a fortified geometric cyber-shield, integrated strike bolt, and CI/CD code bracket nodes.
 */
export function ZeroStrikeLogoIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("size-full shrink-0 select-none", className)}
    >
      <defs>
        {/* Shield Outer Gradient */}
        <linearGradient id="zs-shield-grad" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#10b981" />
          <stop offset="50%" stopColor="#06b6d4" />
          <stop offset="100%" stopColor="#3b82f6" />
        </linearGradient>

        {/* Strike Core Energy Gradient */}
        <linearGradient id="zs-strike-grad" x1="24" y1="8" x2="24" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="50%" stopColor="#10b981" />
          <stop offset="100%" stopColor="#a855f7" />
        </linearGradient>

        {/* Subtle Inner Fill Gradient */}
        <linearGradient id="zs-inner-fill" x1="24" y1="6" x2="24" y2="42" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#10b981" stopOpacity="0.04" />
        </linearGradient>

        {/* Glow Filter */}
        <filter id="zs-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      {/* Background Fortified Shield Contour */}
      <path
        d="M24 4L40 10V22C40 32.5 33.2 40.8 24 44C14.8 40.8 8 32.5 8 22V10L24 4Z"
        fill="url(#zs-inner-fill)"
        stroke="url(#zs-shield-grad)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Left Code Bracket Node (<) */}
      <path
        d="M19 16L14 22L19 28"
        stroke="#38bdf8"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Right Code Bracket Node (>) */}
      <path
        d="M29 16L34 22L29 28"
        stroke="#38bdf8"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Central DevSecOps Strike Bolt (Lightning & Node Target) */}
      <path
        d="M26 10L18 24H25L22 38L32 22H25L26 10Z"
        fill="url(#zs-strike-grad)"
        filter="url(#zs-glow)"
      />

      {/* Center Defense Core Node */}
      <circle cx="24" cy="23" r="1.5" fill="#ffffff" />
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
      {/* Icon Frame */}
      <div
        className={cn(
          "flex items-center justify-center rounded-xl p-1 transition-transform duration-200",
          currentSize.box,
          animated && "hover:scale-105"
        )}
      >
        <ZeroStrikeLogoIcon />
      </div>

      {/* Brand Typography */}
      {showText && (
        <div className="flex flex-col min-w-0">
          <span className={cn("font-bold tracking-tight text-foreground leading-tight", currentSize.text)}>
            Zero<span className="text-primary font-mono">Strike</span>
          </span>
          <span
            className={cn(
              "font-mono font-semibold tracking-widest text-muted-foreground uppercase opacity-75",
              currentSize.sub
            )}
          >
            DevSecOps Platform
          </span>
        </div>
      )}
    </div>
  );
}
