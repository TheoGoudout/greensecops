import { createFileRoute } from "@tanstack/react-router"
import { Container } from "lucide-react"
import type { DockerTargetPublic } from "@/client"
import { DockerService } from "@/client"
import { type TargetList, TargetListPage } from "@/components/TargetListPage"

export const Route = createFileRoute("/_layout/docker/")({
  component: DockerPage,
  head: () => ({
    meta: [{ title: "Docker - GreenSecOps" }],
  }),
})

const DOCKER_TARGETS: TargetList<DockerTargetPublic> = {
  keyPrefix: "docker",
  title: "Docker",
  description:
    "Dockerfile and Compose static analysis, fixes and PRs, per repository.",
  noun: "target",
  pluralLabel: "Docker targets",
  targetLabel: "Docker target",
  icon: Container,
  placeholder: "services/api (blank = repository root)",
  allowRepoRoot: true,
  empty: (
    <>
      No Docker targets configured. Pick a repository and add the folder holding
      its Dockerfile or Compose file (e.g.{" "}
      <code className="font-mono">services/api</code>), or leave the path blank
      to scan the repository root.
    </>
  ),
  repoLink: "/docker/$repoId",
  listTargets: () => DockerService.listTargets({}),
  createTarget: (repoId, rootPath) =>
    DockerService.createTarget({
      requestBody: { repo_id: repoId, root_path: rootPath },
    }),
}

function DockerPage() {
  return <TargetListPage list={DOCKER_TARGETS} />
}
