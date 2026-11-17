import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FRAMEWORK AI",
  description: "AI video editor for people who don't edit: it cuts the ums, retakes and dead air, then you fine-tune on a real timeline.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0d0f14] text-neutral-100 antialiased">{children}</body>
    </html>
  );
}
