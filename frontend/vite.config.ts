import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig, loadEnv } from "vite"

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const repoRoot = path.resolve(__dirname, "..")
  const frontendEnv = loadEnv(mode, __dirname, "")
  const rootEnv = loadEnv(mode, repoRoot, "")
  const viteExplicit =
    process.env.VITE_USER_REGISTRATION_ENABLED ??
    frontendEnv.VITE_USER_REGISTRATION_ENABLED ??
    rootEnv.VITE_USER_REGISTRATION_ENABLED
  const backendStyle =
    process.env.USER_REGISTRATION_ENABLED ??
    frontendEnv.USER_REGISTRATION_ENABLED ??
    rootEnv.USER_REGISTRATION_ENABLED
  if (viteExplicit === undefined && backendStyle !== undefined) {
    process.env.VITE_USER_REGISTRATION_ENABLED =
      backendStyle === "false" ? "false" : "true"
  }

  return {
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    plugins: [
      tanstackRouter({
        target: "react",
        autoCodeSplitting: true,
      }),
      react(),
      tailwindcss(),
    ],
  }
})
