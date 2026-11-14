import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "OKF Studio", description: "Документы и базы знаний в формате OKF" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
