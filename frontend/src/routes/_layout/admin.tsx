import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { Suspense } from "react"

import { RepositoriesService, type UserPublic, UsersService } from "@/client"
import AddExternalRepo from "@/components/Admin/AddExternalRepo"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { DataTable } from "@/components/Common/DataTable"
import PendingUsers from "@/components/Pending/PendingUsers"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"

function getUsersQueryOptions() {
  return {
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 100 }),
    queryKey: ["users"],
  }
}

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Admin - GreenSecOps",
      },
    ],
  }),
})

function UsersTableContent() {
  const { user: currentUser } = useAuth()
  const { data: users } = useSuspenseQuery(getUsersQueryOptions())

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  return <DataTable columns={columns} data={tableData} />
}

function UsersTable() {
  return (
    <Suspense fallback={<PendingUsers />}>
      <UsersTableContent />
    </Suspense>
  )
}

function ExternalReposTab() {
  const { data: repos, isLoading } = useQuery({
    queryKey: ["external-repos"],
    queryFn: () => RepositoriesService.listExternalRepositories({ limit: 100 }),
  })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">External projects</h2>
          <p className="text-sm text-muted-foreground">
            Open-source repositories added for outreach fix PRs
          </p>
        </div>
        <AddExternalRepo />
      </div>
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-6">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !repos?.length ? (
            <p className="text-sm text-muted-foreground p-6 text-center">
              No external repositories yet.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-[1fr_8rem_8rem_9rem] items-center px-6 py-2 border-b text-xs font-medium text-muted-foreground uppercase tracking-wide gap-4">
                <span>Repository</span>
                <span>Default branch</span>
                <span className="text-center">Enabled</span>
                <span className="text-right">Added</span>
              </div>
              <div className="divide-y">
                {repos.map((repo) => (
                  <div
                    key={repo.id}
                    className="grid grid-cols-[1fr_8rem_8rem_9rem] items-center px-6 py-3 gap-4"
                  >
                    <span className="text-xs font-mono truncate">
                      {repo.full_name}
                    </span>
                    <span className="text-xs font-mono text-muted-foreground">
                      {repo.default_branch}
                    </span>
                    <span className="text-center text-xs text-muted-foreground">
                      {repo.enabled ? "Yes" : "No"}
                    </span>
                    <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap text-right">
                      {repo.created_at
                        ? new Date(repo.created_at).toLocaleDateString(
                            undefined,
                            { month: "short", day: "numeric" },
                          )
                        : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function Admin() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Admin</h1>
        <p className="text-muted-foreground">
          Manage users and external projects
        </p>
      </div>
      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="external-projects">External Projects</TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="mt-4">
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-muted-foreground">
              Manage user accounts and permissions
            </p>
            <AddUser />
          </div>
          <UsersTable />
        </TabsContent>
        <TabsContent value="external-projects" className="mt-4">
          <ExternalReposTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
