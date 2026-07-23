import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import {
  Award,
  Boxes,
  CreditCard,
  GitBranch,
  LayoutDashboard,
  ListChecks,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { NavGroup, type NavItem } from "./NavGroup"
import { User } from "./User"

const repoSubItems = [
  { title: "Static analysis", segment: "static-analysis" },
  { title: "Telemetry analysis", segment: "telemetry" },
  { title: "PRs", segment: "pull-requests" },
] as const

function RepoSubNav({ repoId }: { repoId: string }) {
  const { isMobile, setOpenMobile } = useSidebar()
  const currentPath = useRouterState({
    select: (s) => s.location.pathname,
  })

  const handleClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarMenuSub>
      {repoSubItems.map((item) => {
        const href = `/repositories/${repoId}/${item.segment}`
        const isActive = currentPath.startsWith(href)
        return (
          <SidebarMenuSubItem key={item.segment}>
            <SidebarMenuSubButton asChild isActive={isActive}>
              <RouterLink
                to={`/repositories/$repoId/${item.segment}`}
                params={{ repoId }}
                onClick={handleClick}
              >
                {item.title}
              </RouterLink>
            </SidebarMenuSubButton>
          </SidebarMenuSubItem>
        )
      })}
    </SidebarMenuSub>
  )
}

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { isMobile, setOpenMobile } = useSidebar()
  const currentPath = useRouterState({
    select: (s) => s.location.pathname,
  })

  const repoIdMatch = currentPath.match(/^\/repositories\/([^/]+)\/.+$/)
  const currentRepoId = repoIdMatch?.[1] ?? null

  const handleMenuClick = () => {
    if (isMobile) setOpenMobile(false)
  }

  const analysisItems: NavItem[] = [
    {
      icon: GitBranch,
      title: "Repositories",
      path: "/repositories",
      children: currentRepoId ? (
        <RepoSubNav repoId={currentRepoId} />
      ) : undefined,
    },
    { icon: Award, title: "Badges", path: "/badges" },
  ]

  const infrastructureItems: NavItem[] = [
    { icon: Boxes, title: "Terraform", path: "/infrastructure" },
  ]

  const configItems: NavItem[] = [
    { icon: ListChecks, title: "Rules", path: "/rules" },
    { icon: CreditCard, title: "Billing", path: "/billing" },
  ]

  if (currentUser?.is_superuser) {
    configItems.push({ icon: Users, title: "Admin", path: "/admin" })
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  tooltip="Dashboard"
                  isActive={currentPath.startsWith("/dashboard")}
                  asChild
                >
                  <RouterLink to="/dashboard" onClick={handleMenuClick}>
                    <LayoutDashboard />
                    <span>Dashboard</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <NavGroup label="CI/CD Analysis" items={analysisItems} />
        <NavGroup label="Infrastructure" items={infrastructureItems} />
        <NavGroup label="Configuration" items={configItems} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
