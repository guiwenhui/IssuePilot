import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import "./m3.css";
import "./m4.css";
import "./m5.css";
import "./m6.css";

export const metadata: Metadata = {
  title: "IssuePilot｜代码仓库需求交付助手",
  description: "面向小型 Python 开源仓库的需求交付助手。",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN" data-scroll-behavior="smooth">
      <body>{children}</body>
    </html>
  );
}
