import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Facturation | Console",
  description: "Console de pilotage de votre infrastructure de facturation"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body>{children}</body></html>;
}
