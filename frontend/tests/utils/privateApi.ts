// Note: the `PrivateService` is only available when generating the client
// for local environments
import { OpenAPI, PrivateService } from "../../src/client"

export const createUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  OpenAPI.BASE = process.env.VITE_API_URL?.trim() || "http://localhost:8000"
  return await PrivateService.createUser({
    requestBody: {
      email,
      password,
      is_verified: true,
      full_name: "Test User",
    },
  })
}
