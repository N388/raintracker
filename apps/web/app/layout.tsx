import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "مطر — أمطار السعودية التاريخية",
  description: "خريطة تفاعلية لأمطار المملكة: الوسم، الفياض، الربيع",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
