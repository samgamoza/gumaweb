import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "GumaWeb", template: "%s · GumaWeb" },
  description: "We already built your website. Claim it.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh font-sans">{children}</body>
    </html>
  );
}
