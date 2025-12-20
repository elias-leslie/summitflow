import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { AppShell } from "@/components/layout/AppShell";

export const metadata: Metadata = {
  title: "SummitFlow",
  description: "AI-assisted software development platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        <Providers>
          <div className="flex h-screen overflow-hidden">
            {/* Sidebar */}
            <Sidebar />

            {/* Main content area */}
            <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
              <TopBar />
              <AppShell>
                <main className="flex-1 overflow-auto bg-grid">
                  {children}
                </main>
              </AppShell>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
