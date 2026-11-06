import type { Metadata } from "next";
import { headers } from "next/headers";
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
  title: "thinkShield Portal",
  description: "Application security scanning, findings, and remediation.",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Reading the request headers also makes every page render per request, which the nonce needs: it
  // is minted per request in proxy.ts, and a page built ahead of time would ship scripts the browser
  // then refuses to run.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${jetbrainsMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        <AppProviders nonce={nonce}>{children}</AppProviders>
      </body>
    </html>
  );
}
