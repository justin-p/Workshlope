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
    <html lang="en">
      <body
        style={{
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
          margin: 0,
        }}
      >
        {children}
      </body>
    </html>
  )
}
