import { LogOut } from "lucide-react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { getInitials } from "@/utils"

export function User({ user }: { user: any }) {
  const { logout } = useAuth()

  if (!user) return null

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton size="lg" onClick={logout}>
          <Avatar className="size-8">
            <AvatarFallback className="bg-primary text-primary-foreground text-xs font-semibold">
              {getInitials(user?.full_name || "User")}
            </AvatarFallback>
          </Avatar>
          <div className="flex flex-col items-start min-w-0">
            <p className="text-sm font-medium truncate w-full">
              {user?.full_name}
            </p>
            <p className="text-xs text-muted-foreground truncate w-full">
              {user?.email}
            </p>
          </div>
          <LogOut className="ml-auto size-4 text-muted-foreground" />
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
