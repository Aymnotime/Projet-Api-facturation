import type { Metadata } from "next";
import { Inter } from 'next/font/google';
import "./globals.css";

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: "FacturEasy - Facturation Électronique",
  description: "Plateforme de facturation électronique conforme EN 16931"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body className={inter.className}>{children}</body></html>;
}
