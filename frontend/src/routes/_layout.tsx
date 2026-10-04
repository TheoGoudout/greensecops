import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"
import { useRepoEvents } from "@/hooks/useRepoEvents"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  useRepoEvents()

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="bg-tech-grid">
        <header className="sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 bg-background/75 px-4 backdrop-blur">
          <span
            aria-hidden="true"
            className="bg-signal pointer-events-none absolute inset-x-0 bottom-0 h-0.5"
          />
          <SidebarTrigger className="-ml-1 text-muted-foreground" />
        </header>
        <main className="flex-1 p-6 md:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
