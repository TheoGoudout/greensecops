import { Link } from "@tanstack/react-router"

import { useTheme } from "@/components/theme-provider"
import { cn } from "@/lib/utils"
import logoFull from "/assets/images/logo-full.png"
import logoFullDark from "/assets/images/logo-full-dark.png"
import logoMark from "/assets/images/logo-mark.png"
import logoMarkDark from "/assets/images/logo-mark-dark.png"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
  /** Sits on a dark surface (the sidebar) whatever the theme. */
  onDark?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
  onDark = false,
}: LogoProps) {
  const { resolvedTheme } = useTheme()
  const isDark = onDark || resolvedTheme === "dark"

  const fullLogo = isDark ? logoFullDark : logoFull
  const iconLogo = isDark ? logoMarkDark : logoMark

  const content =
    variant === "responsive" ? (
      <>
        <img
          src={fullLogo}
          alt="GreenSecOps"
          className={cn(
            "h-6 w-auto group-data-[collapsible=icon]:hidden",
            className,
          )}
        />
        <img
          src={iconLogo}
          alt="GreenSecOps"
          className={cn(
            "size-5 hidden group-data-[collapsible=icon]:block",
            className,
          )}
        />
      </>
    ) : (
      <img
        src={variant === "full" ? fullLogo : iconLogo}
        alt="GreenSecOps"
        className={cn(variant === "full" ? "h-6 w-auto" : "size-5", className)}
      />
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
