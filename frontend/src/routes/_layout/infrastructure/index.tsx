import { createFileRoute } from "@tanstack/react-router"
import { Boxes } from "lucide-react"
import type { TerraformRootPublic } from "@/client"
import { TerraformService } from "@/client"
import { type TargetList, TargetListPage } from "@/components/TargetListPage"

export const Route = createFileRoute("/_layout/infrastructure/")({
  component: InfrastructurePage,
  head: () => ({
    meta: [{ title: "Infrastructure - GreenSecOps" }],
  }),
})

const TERRAFORM_ROOTS: TargetList<TerraformRootPublic> = {
  keyPrefix: "terraform",
  title: "Terraform",
  description: "Terraform roots, cloud posture and fixes, per repository.",
  noun: "root",
  pluralLabel: "Terraform roots",
  targetLabel: "Terraform root",
  icon: Boxes,
  placeholder: "infra/prod",
  // A root must name a folder; the repository root is not one.
  allowRepoRoot: false,
  empty: (
    <>
      No Terraform roots configured. Pick a repository and add a folder path
      where your Terraform code lives (e.g.{" "}
      <code className="font-mono">infra</code> or{" "}
      <code className="font-mono">terraform/prod</code>) to start.
    </>
  ),
  repoLink: "/infrastructure/$repoId",
  listTargets: () => TerraformService.listRoots({}),
  createTarget: (repoId, rootPath) =>
    TerraformService.createRoot({
      requestBody: { repo_id: repoId, root_path: rootPath },
    }),
}

function InfrastructurePage() {
  return <TargetListPage list={TERRAFORM_ROOTS} />
}
