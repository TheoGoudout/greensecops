import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"
import { RepositoriesService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export default function AddExternalRepo() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [fullName, setFullName] = useState("")
  const [installationId, setInstallationId] = useState("")

  const mutation = useMutation({
    mutationFn: () =>
      RepositoriesService.createExternalRepository({
        requestBody: {
          full_name: fullName.trim(),
          installation_id: installationId ? Number(installationId) : null,
        },
      }),
    onSuccess: (repo) => {
      toast.success(`Added ${repo.full_name}`)
      queryClient.invalidateQueries({ queryKey: ["external-repos"] })
      setOpen(false)
      setFullName("")
      setInstallationId("")
    },
    onError: () => toast.error("Failed to add external repository"),
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!fullName.trim()) return
    mutation.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">Add project</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add external repository</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 mt-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="full-name">Repository (owner/repo)</Label>
            <Input
              id="full-name"
              placeholder="facebook/react"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="installation-id">
              GitHub App installation ID{" "}
              <span className="text-muted-foreground font-normal">
                (optional)
              </span>
            </Label>
            <Input
              id="installation-id"
              type="number"
              placeholder="12345678"
              value={installationId}
              onChange={(e) => setInstallationId(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Leave blank to register now — automated fix delivery requires the
              repo owner to install the GreenSecOps GitHub App first.
            </p>
          </div>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Adding…" : "Add repository"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
