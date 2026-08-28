import type { Metadata } from "next"; import { Inter, Manrope } from "next/font/google"; import "./globals.css";
import "./master-research.css"; import "./product-ui.css";
const inter=Inter({subsets:["latin"],variable:"--font-body"}); const manrope=Manrope({subsets:["latin"],variable:"--font-display"});
export const metadata:Metadata={title:"FlexMap | Posture Rehabilitation System",description:"Patient-friendly posture readiness interface"};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body className={`${inter.variable} ${manrope.variable}`}>{children}</body></html>}
