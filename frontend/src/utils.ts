import { AxiosError } from "axios"
import { toast } from "sonner"
import { ApiError } from "./client"

function extractErrorMessage(err: ApiError): string {
  if (err instanceof AxiosError) {
    return err.message
  }

  const errDetail = (err.body as any)?.detail
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    return errDetail[0].msg
  }
  return errDetail || "Something went wrong."
}

export function showSuccessToast(description: string) {
  toast.success("Success!", { description })
}

export function showErrorToast(description: string) {
  toast.error("Something went wrong!", { description })
}

/** Show the standard error toast with the message extracted from an ApiError. */
export function handleApiError(err: ApiError) {
  showErrorToast(extractErrorMessage(err))
}

export function apiErrorDetail(error: unknown): string | undefined {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown })?.detail
    if (typeof detail === "string") return detail
  }
  return undefined
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}
