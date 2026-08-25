import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"

import {
  type Body_login_login_access_token as AccessToken,
  type ApiError,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "@/client"
import { handleApiError, showSuccessToast } from "@/lib/toast"

const isLoggedIn = () => {
  return localStorage.getItem("access_token") !== null
}

const useAuth = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: user, error: userError } = useQuery<
    UserPublic | null,
    ApiError
  >({
    queryKey: ["currentUser"],
    queryFn: UsersService.readUserMe,
    enabled: isLoggedIn(),
    retry: (failureCount, error) =>
      ![400, 403, 404].includes(error.status) && failureCount < 3,
  })

  const signUpMutation = useMutation({
    mutationFn: (data: UserRegister) =>
      UsersService.registerUser({ requestBody: data }),
    onSuccess: () => {
      navigate({ to: "/login" })
    },
    onError: handleApiError,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const login = async (data: AccessToken) => {
    const response = await LoginService.loginAccessToken({
      formData: data,
    })
    localStorage.setItem("access_token", response.access_token)
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: () => {
      showSuccessToast("Welcome back, nice to see you again!")
      const pending = sessionStorage.getItem("pending_installation")
      if (pending) {
        sessionStorage.removeItem("pending_installation")
        try {
          const params = JSON.parse(pending) as Record<string, unknown>
          navigate({ to: "/auth/github/app-callback", search: params })
          return
        } catch {
          // malformed entry — fall through to default redirect
        }
      }
      navigate({ to: "/" })
    },
    onError: handleApiError,
  })

  const logout = () => {
    localStorage.removeItem("access_token")
    navigate({ to: "/login" })
  }

  useEffect(() => {
    if (userError && [400, 403, 404].includes(userError.status)) {
      localStorage.removeItem("access_token")
      navigate({ to: "/login" })
    }
  }, [userError, navigate])

  return {
    signUpMutation,
    loginMutation,
    logout,
    user,
  }
}

export { isLoggedIn }
export default useAuth
