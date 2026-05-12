import hljs from "highlight.js/lib/core"
import bash from "highlight.js/lib/languages/bash"
import javascript from "highlight.js/lib/languages/javascript"
import json from "highlight.js/lib/languages/json"
import markdown from "highlight.js/lib/languages/markdown"
import plaintext from "highlight.js/lib/languages/plaintext"
import python from "highlight.js/lib/languages/python"
import sql from "highlight.js/lib/languages/sql"
import typescript from "highlight.js/lib/languages/typescript"
import yaml from "highlight.js/lib/languages/yaml"
import { type ComponentPropsWithoutRef, useLayoutEffect, useRef } from "react"
import { toast } from "sonner"

import { cn } from "@/lib/utils"

let hljsRegistered = false

function registerHighlightLanguages(): void {
  if (hljsRegistered) return
  hljsRegistered = true
  hljs.registerLanguage("bash", bash)
  hljs.registerLanguage("sh", bash)
  hljs.registerLanguage("shell", bash)
  hljs.registerLanguage("zsh", bash)
  hljs.registerLanguage("javascript", javascript)
  hljs.registerLanguage("js", javascript)
  hljs.registerLanguage("jsx", javascript)
  hljs.registerLanguage("typescript", typescript)
  hljs.registerLanguage("ts", typescript)
  hljs.registerLanguage("tsx", typescript)
  hljs.registerLanguage("python", python)
  hljs.registerLanguage("py", python)
  hljs.registerLanguage("json", json)
  hljs.registerLanguage("yaml", yaml)
  hljs.registerLanguage("yml", yaml)
  hljs.registerLanguage("markdown", markdown)
  hljs.registerLanguage("md", markdown)
  hljs.registerLanguage("sql", sql)
  hljs.registerLanguage("text", plaintext)
  hljs.registerLanguage("plaintext", plaintext)
  hljs.registerLanguage("txt", plaintext)
}

export type WorkshopMarkdownHtmlProps = {
  html: string
  className?: string
} & Omit<
  ComponentPropsWithoutRef<"article">,
  "children" | "dangerouslySetInnerHTML"
>

/** nh3-sanitized lesson HTML: syntax highlight fenced blocks and add copy buttons. */
export function WorkshopMarkdownHtml({
  html,
  className,
  ...articleProps
}: WorkshopMarkdownHtmlProps) {
  const rootRef = useRef<HTMLElement | null>(null)

  useLayoutEffect(() => {
    registerHighlightLanguages()
    const root = rootRef.current
    if (!root) return

    root.innerHTML = html

    const pres = Array.from(root.querySelectorAll("pre"))
    let firstCopyButton = true
    for (const pre of pres) {
      const code = pre.querySelector(":scope > code")
      if (!(code instanceof HTMLElement)) return
      if (pre.parentElement?.classList.contains("workshop-code-block")) return

      const wrap = document.createElement("div")
      wrap.className =
        "workshop-code-block relative my-4 rounded-md border border-border group"
      pre.replaceWith(wrap)
      wrap.appendChild(pre)

      try {
        hljs.highlightElement(code)
      } catch {
        /* unknown or invalid grammar */
      }

      const btn = document.createElement("button")
      btn.type = "button"
      btn.setAttribute("aria-label", "Copy code")
      if (firstCopyButton) {
        btn.setAttribute("data-testid", "workshop-code-copy")
        firstCopyButton = false
      }
      btn.className =
        "absolute right-2 top-2 z-10 rounded border border-border bg-card/95 px-2 py-1 text-xs font-medium text-foreground shadow-sm backdrop-blur-sm hover:bg-muted/80"
      btn.textContent = "Copy"
      btn.addEventListener("click", () => {
        void (async () => {
          try {
            await navigator.clipboard.writeText(code.innerText)
            toast.success("Copied to clipboard")
          } catch {
            toast.error("Could not copy")
          }
        })()
      })
      wrap.appendChild(btn)
    }

    return () => {
      root.innerHTML = ""
    }
  }, [html])

  return (
    <article
      ref={rootRef}
      className={cn("workshop-markdown max-w-none", className)}
      {...articleProps}
    />
  )
}
