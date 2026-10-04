import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { AuthShowcase } from "./AuthShowcase"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="min-h-svh bg-background bg-tech-grid flex items-center justify-center gap-16 p-4">
      <div className="absolute top-4 right-4">
        <Appearance />
      </div>
      <AuthShowcase />
      <div className="bg-card border rounded-xl shadow-sm p-8 w-full max-w-sm">
        <div className="flex flex-col items-center gap-2 mb-6">
          <Logo variant="icon" asLink={false} className="size-12" />
          <span className="font-display text-lg font-semibold tracking-tight text-foreground">
            GreenSecOps
          </span>
        </div>
        {children}
      </div>
    </div>
  )
}
