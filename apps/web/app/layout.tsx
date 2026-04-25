import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "字幕制作スイート",
  description: "AI subtitle generation, translation, and editing — Mac-first",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja" className="dark">
      <body>{children}</body>
    </html>
  );
}
