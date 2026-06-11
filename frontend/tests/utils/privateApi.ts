// Note: the `PrivateService` is only available when generating the client
// for local environments
import { OpenAPI, PrivateService } from "../../src/client"

OpenAPI.BASE = `${process.env.VITE_API_URL}`

async function withRetry<T>(
  fn: () => Promise<T>,
  retries = 3,
  delayMs = 500,
): Promise<T> {
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      return await fn()
    } catch (err) {
      if (attempt === retries - 1) throw err
      await new Promise((r) => setTimeout(r, delayMs * (attempt + 1)))
    }
  }
  throw new Error("unreachable")
}

export const createUser = async ({
  email,
  password,
}: {
  email: string
  password: string
}) => {
  return await withRetry(() =>
    PrivateService.createUser({
      requestBody: {
        email,
        password,
        is_verified: true,
        full_name: "Test User",
      },
    }),
  )
}
