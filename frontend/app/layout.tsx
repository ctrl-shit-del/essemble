import type { Metadata, Viewport } from "next";
import { Fraunces, Manrope } from "next/font/google";
import { Providers } from "./providers";
import "./globals.css";

/**
 * Typography.
 *
 * Fraunces for display: a high-contrast variable serif with a soft optical
 * axis, so titles carry the warmth of a cinema marquee rather than the
 * neutrality of a dashboard. Deliberately not Inter or system-ui -- those
 * read as "generic web app", which is exactly the impression this product
 * cannot afford.
 *
 * Manrope for UI: geometric, slightly rounded, and unusually legible at 13px,
 * which is where most of this interface lives.
 */
const display = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
  // The optical-size and softness axes are what give it character; without
  // them Fraunces renders close to a default serif. Weight is deliberately
  // absent -- next/font only allows custom axes on a fully variable face, so
  // naming weights here would pin the font to static instances and drop the
  // axes entirely.
  axes: ["SOFT", "WONK", "opsz"],
});

const sans = Manrope({
  subsets: ["latin"],
  variable: "--font-manrope",
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: {
    default: "ESSEMBLE",
    template: "%s · ESSEMBLE",
  },
  description:
    "Book seats for films and live events. Real-time seat maps, honest availability.",
};

export const viewport: Viewport = {
  themeColor: "#0D0D0F",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning: the browser's own extensions commonly stamp
    // attributes onto <html> before React hydrates.
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`${sans.variable} ${display.variable} antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
