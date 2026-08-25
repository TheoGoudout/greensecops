import { toast } from "sonner"
import type { ApiError } from "@/client"
import { extractErrorMessage } from "@/lib/api-error"

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
