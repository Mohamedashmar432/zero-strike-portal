import type { Metadata } from "next";
import { Archivo, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AppProviders } from "@/providers/app-providers";

/**
 * Signal Room type pairing.
 *
 * Archivo — an industrial grotesque with tight apertures and a tall x-height.
 * Holds up at 11-12px in dense tables (where this app spends most of its time)
 * without the anonymous, every-startup feel of Inter or Hanken Grotesk.
 *
 * JetBrains Mono — carries every heading, metric readout, badge and micro-label,
 * not just code. Security engineers read hashes, CVE ids, file paths and line
 * numbers all day; making mono the *display* face states what the tool is
 * instead of decorating it. Slashed zero via `ss01`/`zero` (see globals.css).
 */
const archivo = Archivo({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "ZeroStrike Portal",
  description: "SAST scan orchestration, projects, and findings.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${jetbrainsMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
