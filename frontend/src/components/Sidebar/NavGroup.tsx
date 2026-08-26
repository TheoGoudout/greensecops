import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type NavItem = {
  icon: LucideIcon
  title: string
  path: string
  children?: ReactNode
  /**
   * Override the default "current path starts with `path`" rule.
   *
   * Needed when two entries share a path prefix: Terraform sits at
   * `/infrastructure` and Ansible at `/infrastructure/ansible`, so the prefix
   * rule alone lights Terraform up on every Ansible page and never lights up
   * Ansible on a per-repo tab. The caller knows which engine's tab is open;
   * NavGroup does not.
   */
  isActive?: boolean
}

interface NavGroupProps {
  label: string
  items: NavItem[]
}

export function NavGroup({ label, items }: NavGroupProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const currentPath = useRouterState({
    select: (s) => s.location.pathname,
  })

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarGroup>
      <SidebarGroupLabel>{label}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const isActive = item.isActive ?? currentPath.startsWith(item.path)

            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  tooltip={item.title}
                  isActive={isActive}
                  asChild
                >
                  <RouterLink to={item.path} onClick={handleMenuClick}>
                    <item.icon />
                    <span>{item.title}</span>
                  </RouterLink>
                </SidebarMenuButton>
                {item.children}
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
