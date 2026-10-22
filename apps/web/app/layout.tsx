import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "مطر — أمطار السعودية التاريخية",
  description: "خريطة تفاعلية لأمطار المملكة: الوسم، الفياض، الربيع",
};

// عرض الهاتف: بدون هذا السطر تُعرض الصفحة بعرض سطح المكتب وتبدو مكبّرة ومكسورة
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
