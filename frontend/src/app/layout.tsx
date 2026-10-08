import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Astra — Clinical trial reporting, under a clearer lens",
  description:
    "Astra uses six AI specialists, evidence checks, and human review to examine how clinical trials report their results.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
