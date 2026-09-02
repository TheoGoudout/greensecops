import type { ReactNode } from "react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/**
 * The one confirm every engine's "Remove" goes through.
 *
 * Terraform, Docker, Ansible and Cloud each called `window.confirm` with their
 * own sentence, which is untestable, unstyleable, and — on Docker — attached to
 * an unlabelled trash icon. Controlled rather than trigger-based, because the
 * button that opens it now lives inside a dropdown menu that closes on select.
 */
export function ConfirmRemoveDialog({
  open,
  onOpenChange,
  /** What is being removed, e.g. `infra/prod`. */
  name,
  /** Noun for the title: "Terraform root", "cloud account". */
  targetLabel,
  /** What else goes with it, so the choice is informed. */
  description,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  name: string
  targetLabel: string
  description?: ReactNode
  onConfirm: () => void
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            Remove {targetLabel.toLowerCase()}{" "}
            <span className="font-mono">{name}</span>?
          </AlertDialogTitle>
          <AlertDialogDescription>
            {description ??
              "This deletes its scan history, findings and fixes. It cannot be undone."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={cn(buttonVariants({ variant: "destructive" }))}
            onClick={onConfirm}
          >
            Remove
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
