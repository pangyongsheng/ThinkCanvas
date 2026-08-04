import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ThinkCanvas",
  description: "AI + Manim 算法动画生成器",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" className="bg-gray-950">
      <body className="bg-gray-950 text-white antialiased">{children}</body>
    </html>
  );
}
