/** @type {import('next').NextConfig} */
const basePath =
  process.env.NEXT_BASE_PATH?.replace(/\/$/, "") || ""

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  ...(basePath ? { basePath } : {}),
}

export default nextConfig
