import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import {
  Award,
  Boxes,
  Container,
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

const infraSubItems = [
  // "Analysis" rather than "Terraform": the parent item already names the
  // engine, and nesting the same word under itself reads as a broken link.
  // Mirrors the Docker section's Analysis tab.
  { title: "Analysis", segment: "terraform" },
  { title: "Ansible", segment: "ansible" },
  { title: "Cloud", segment: "cloud" },
  { title: "PRs", segment: "pull-requests" },
] as const

function InfraSubNav({ repoId }: { repoId: string }) {
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
      {infraSubItems.map((item) => {
        const href = `/infrastructure/${repoId}/${item.segment}`
        const isActive = currentPath.startsWith(href)
        return (
          <SidebarMenuSubItem key={item.segment}>
            <SidebarMenuSubButton asChild isActive={isActive}>
              <RouterLink
                to={`/infrastructure/$repoId/${item.segment}`}
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

const dockerSubItems = [
  { title: "Analysis", segment: "analysis" },
  { title: "Runtime", segment: "runtime" },
  { title: "PRs", segment: "pull-requests" },
  { title: "Scan history", segment: "scans" },
] as const

function DockerSubNav({ repoId }: { repoId: string }) {
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
      {dockerSubItems.map((item) => {
        const href = `/docker/${repoId}/${item.segment}`
        const isActive = currentPath.startsWith(href)
        return (
          <SidebarMenuSubItem key={item.segment}>
            <SidebarMenuSubButton asChild isActive={isActive}>
              <RouterLink
                to={`/docker/$repoId/${item.segment}`}
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

  const infraRepoMatch = currentPath.match(
    /^\/infrastructure\/([^/]+)(?:\/.+)?$/,
  )
  // "badges" is a static sibling route, not a repo id.
  const currentInfraRepoId =
    infraRepoMatch && infraRepoMatch[1] !== "badges" ? infraRepoMatch[1] : null

  const dockerRepoMatch = currentPath.match(/^\/docker\/([^/]+)(?:\/.+)?$/)
  // "badges" is a static sibling route, not a repo id.
  const currentDockerRepoId =
    dockerRepoMatch && dockerRepoMatch[1] !== "badges"
      ? dockerRepoMatch[1]
      : null

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
  ]

  const infrastructureItems: NavItem[] = [
    {
      // Named for what the page lists — Terraform roots — rather than
      // repeating the group label. Cloud posture lives as a tab within it.
      icon: Boxes,
      title: "Terraform",
      path: "/infrastructure",
      children: currentInfraRepoId ? (
        <InfraSubNav repoId={currentInfraRepoId} />
      ) : undefined,
    },
  ]

  const containerItems: NavItem[] = [
    {
      icon: Container,
      title: "Docker",
      path: "/docker",
      children: currentDockerRepoId ? (
        <DockerSubNav repoId={currentDockerRepoId} />
      ) : undefined,
    },
  ]

  // Cross-cutting, like the dashboard: one page with a tab per engine rather
  // than an entry inside each engine's group.
  const overviewItems: NavItem[] = [
    { icon: LayoutDashboard, title: "Dashboard", path: "/dashboard" },
    { icon: Award, title: "Badges", path: "/badges" },
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
              {overviewItems.map((item) => (
                <SidebarMenuItem key={item.path}>
                  <SidebarMenuButton
                    tooltip={item.title}
                    isActive={currentPath.startsWith(item.path)}
                    asChild
                  >
                    <RouterLink to={item.path} onClick={handleMenuClick}>
                      <item.icon />
                      <span>{item.title}</span>
                    </RouterLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        {/* Ordered as the pipeline runs: build, package, then run. Both
            auto-populated sections sit above the two that stay empty until
            someone registers a Terraform root or connects a cloud account. */}
        <NavGroup label="CI/CD Analysis" items={analysisItems} />
        <NavGroup label="Containers" items={containerItems} />
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
