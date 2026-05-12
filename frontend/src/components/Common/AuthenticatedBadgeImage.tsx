// Loads badge artwork via authenticated fetch (Bearer); plain <img src> cannot attach the SPA token.
import { useEffect, useState } from "react"

import { OpenAPI } from "@/client"

const DEFAULT_BADGE = "/badge-default.svg"

type AuthenticatedBadgeImageProps = {
  badgeId: string
  alt?: string
  width?: number
  height?: number
  className?: string
  "data-testid"?: string
}

export function AuthenticatedBadgeImage({
  badgeId,
  alt = "",
  width = 40,
  height = 40,
  className,
  "data-testid": dataTestId,
}: AuthenticatedBadgeImageProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    let createdUrl: string | null = null

    const run = async () => {
      setFailed(false)
      setObjectUrl(null)
      const token = localStorage.getItem("access_token") ?? ""
      const base = OpenAPI.BASE?.replace(/\/$/, "") ?? ""
      const res = await fetch(
        `${base}/api/v1/workshop/badges/${encodeURIComponent(badgeId)}/image`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          credentials:
            OpenAPI.CREDENTIALS === "include" ? "include" : "same-origin",
        },
      )
      if (cancelled) return
      if (!res.ok) {
        setFailed(true)
        return
      }
      const blob = await res.blob()
      if (cancelled) return
      createdUrl = URL.createObjectURL(blob)
      setObjectUrl(createdUrl)
    }

    void run().catch(() => {
      if (!cancelled) setFailed(true)
    })

    return () => {
      cancelled = true
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [badgeId])

  const src = failed || !objectUrl ? DEFAULT_BADGE : objectUrl

  return (
    <img
      src={src}
      alt={alt}
      width={width}
      height={height}
      className={className}
      data-testid={dataTestId}
    />
  )
}
