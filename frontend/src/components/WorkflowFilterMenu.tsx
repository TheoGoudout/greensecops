import { SlidersHorizontal } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

/**
 * The workflow page's two issue filters, folded into one control.
 *
 * They were two buttons in the action row, faking their on/off state with
 * `variant={on ? "default" : "outline"}` — indistinguishable at a glance from
 * the real actions beside them, which is most of why that row read as eight
 * buttons. A menu says "these are filters", and the badge says how many are on
 * without opening it.
 */
export function WorkflowFilterMenu({
  openOnly,
  onOpenOnlyChange,
  showIgnored,
  onShowIgnoredChange,
}: {
  openOnly: boolean
  onOpenOnlyChange: (value: boolean) => void
  showIgnored: boolean
  onShowIgnoredChange: (value: boolean) => void
}) {
  const active = Number(openOnly) + Number(showIgnored)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1.5">
          <SlidersHorizontal className="h-4 w-4" />
          Filters
          {active > 0 && (
            <Badge variant="secondary" className="ml-0.5 px-1.5 tabular-nums">
              {active}
            </Badge>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuLabel>Issues</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem
          checked={openOnly}
          onCheckedChange={onOpenOnlyChange}
        >
          Open issues only
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem
          checked={showIgnored}
          onCheckedChange={onShowIgnoredChange}
        >
          Include ignored
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
