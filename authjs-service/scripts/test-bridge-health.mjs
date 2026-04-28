const endpoint = process.env.AUTHJS_HEALTH_URL ?? "http://localhost:3001/api/bridge/health"

async function main() {
  const response = await fetch(endpoint)
  if (!response.ok) {
    throw new Error(`Health endpoint returned ${response.status}`)
  }

  const body = await response.json()
  if (!body.ok) {
    throw new Error("Health endpoint reported ok=false")
  }
  if (body.service !== "authjs-bridge") {
    throw new Error(`Unexpected service value: ${body.service}`)
  }
  if (!body.checks?.bridge_signing) {
    throw new Error("Bridge signing check failed")
  }

  console.log("Auth.js bridge health check passed")
  console.log(JSON.stringify(body))
}

main().catch((err) => {
  console.error("Auth.js bridge health check failed")
  console.error(err instanceof Error ? err.message : err)
  process.exit(1)
})
