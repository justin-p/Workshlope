import "./globals.css"

import { themeInitScript } from "../lib/theme-init-script"

export const metadata = {
  title: "Auth Bridge",
  description: "GitHub OAuth bridge for the FastAPI app",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <script
          // Applies dark/light before paint; matches frontend ThemeProvider defaults.
          dangerouslySetInnerHTML={{ __html: themeInitScript }}
        />
        {children}
      </body>
    </html>
  )
}
