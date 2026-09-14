import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PARADIGM INTELLIGENCE — Top 50 Opportunities",
  description:
    "The 50 corporate sales opportunities most likely to generate event business for PARADIGM in Egypt.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
