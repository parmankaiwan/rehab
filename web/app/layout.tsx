import type { Metadata } from "next";
import { Inter, Manrope } from "next/font/google";
import "./globals.css";
import "./emg-live.css";
import "./master-research.css";
import "./product-ui.css";
import "./emg-drawer.css";
import "./emg-details.css";
import "./design-system.css";
import "./aesthetic-theme.css";
import "./ml-workflow.css";
import "./emg-collection.css";
import "./emg-validation.css";
import "./acquisition-countdown.css";
import "./vault-actions.css";
import "./browser-pose.css";
const inter = Inter({ subsets: ["latin"], variable: "--font-body" });
const manrope = Manrope({ subsets: ["latin"], variable: "--font-display" });
export const metadata: Metadata = {
  title: "FlexMap | Posture Rehabilitation System",
  description: "Patient-friendly posture readiness interface",
  icons: {
    icon: "/favicon.ico",
  },
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${manrope.variable}`}>
        {children}
      </body>
    </html>
  );
}
