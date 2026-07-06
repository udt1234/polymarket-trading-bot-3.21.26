import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Polymarket Maker Terminal",
  description: "Read-only trading terminal for the Polymarket maker bot",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-term-bg font-mono text-sm text-term-text antialiased">
        {children}
      </body>
    </html>
  );
}
