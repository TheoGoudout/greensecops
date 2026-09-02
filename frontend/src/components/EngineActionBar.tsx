import { Loader2, type LucideIcon, MoreHorizontal } from "lucide-react"
import type { ReactNode } from "react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { EngineAction, EngineActionId } from "@/lib/engine-actions"
import { cn } from "@/lib/utils"

/**
 * The row of actions every engine target carries.
 *
 * Terraform, Docker, Ansible, Cloud and the CI-workflow engine each wrote their
 * own, and they drifted: the same action appeared as "Run analysis", "Re-analyze"
 * and "Scan now"; "Generate all fixes" was a `Zap` on two engines and a `Wand2`
 * on a third; Docker's delivery button was solid where Terraform's was outline,
 * and its Remove was an unlabelled trash icon. This is one bar, so learning one
 * engine's controls is learning all of them.
 *
 * What each button *says* and whether it is live comes from
 * `lib/engine-actions.ts`; this component only draws it.
 */

export interface OverflowItem {
  label: string
  icon: LucideIcon
  onSelect: () => void
  /** Renders in the destructive colour and sits below a divider. */
  destructive?: boolean
  disabled?: boolean
  /** Shown when disabled, in the same tooltip the three buttons use. */
  reason?: string | null
}

/**
 * An `EngineAction` as an overflow item.
 *
 * Removing a target and re-syncing a repository are ruled on by the same table
 * the three buttons obey (`lib/engine-actions`), they just belong in a menu
 * rather than the row. This is the adapter, so a caller never rebuilds
 * `disabled` and `reason` by hand next to an action that already carries them.
 */
export function overflowItem(
  action: EngineAction,
  onSelect: () => void,
  extra: { destructive?: boolean; label?: string } = {},
): OverflowItem {
  return {
    label: extra.label ?? action.label,
    icon: action.icon,
    onSelect,
    destructive: extra.destructive,
    disabled: action.disabled,
    reason: action.reason,
  }
}

export interface EngineActionBarProps {
  actions: Record<EngineActionId, EngineAction>
  /**
   * Which of the three this engine has at all. Cloud posture has no files to
   * rewrite, so it declares neither `generate` nor `deliver` rather than
   * showing two permanently dead buttons.
   */
  capabilities?: Partial<Record<EngineActionId, boolean>>
  onScan?: () => void
  onGenerate?: () => void
  onDeliver?: () => void
  /**
   * `page` for a repository-wide bar above a list, `card` for one inside a
   * target's header — the same controls at two densities.
   */
  size?: "page" | "card"
  /** Rendered before the actions: an enable switch, a status pill. */
  leading?: ReactNode
  /** Rendered after them: the workflow page's filter menu. */
  trailing?: ReactNode
  overflow?: OverflowItem[]
  /**
   * Names this bar for tests. Every engine now shows the same three labels, so
   * a page carrying both a repository-wide bar and one per target card has two
   * "Scan now" buttons that differ only in scope — which is the point, and
   * which a label alone cannot disambiguate.
   */
  testId?: string
}

/**
 * One action, drawn.
 *
 * Exported because the per-file "Generate fix" buttons inside a card are the
 * same button at a narrower scope — they get their state from `engineActions`
 * exactly as the bar does, and should look and explain themselves the same way.
 *
 * A disabled `<button>` receives no pointer events, so its tooltip would never
 * open. Wrapping it in a focusable span gives the trigger something live to
 * hang off — which also makes the reason reachable from the keyboard.
 */
export function EngineActionButton({
  action,
  onClick,
  compact = false,
  variant = "outline",
}: {
  action: EngineAction
  onClick?: () => void
  compact?: boolean
  variant?: "outline" | "ghost"
}) {
  const Icon = action.icon
  const button = (
    <Button
      size="sm"
      variant={variant}
      className={cn("gap-1.5", compact && "h-7 text-xs")}
      disabled={action.disabled}
      onClick={onClick}
    >
      {action.busy ? (
        <Loader2
          className={cn("animate-spin", compact ? "h-3 w-3" : "h-4 w-4")}
        />
      ) : (
        <Icon className={compact ? "h-3 w-3" : "h-4 w-4"} />
      )}
      {action.label}
    </Button>
  )
  if (!action.reason) return button
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex">{button}</span>
      </TooltipTrigger>
      <TooltipContent>{action.reason}</TooltipContent>
    </Tooltip>
  )
}

/**
 * One overflow item, drawn.
 *
 * A disabled `DropdownMenuItem` receives no pointer events, so — exactly as
 * with a disabled `<button>` — its reason needs a live wrapper to hang off.
 * These used to fall back to a native `title`, which meant the one place the
 * bar explains a destructive action was also the one place the explanation
 * looked different and could not be reached from the keyboard.
 */
function OverflowMenuItem({ item }: { item: OverflowItem }) {
  const element = (
    <DropdownMenuItem
      variant={item.destructive ? "destructive" : "default"}
      disabled={item.disabled}
      onSelect={item.onSelect}
    >
      <item.icon className="h-4 w-4" />
      {item.label}
    </DropdownMenuItem>
  )
  if (!item.disabled || !item.reason) return element
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex w-full">{element}</span>
      </TooltipTrigger>
      <TooltipContent side="left">{item.reason}</TooltipContent>
    </Tooltip>
  )
}

export function EngineActionBar({
  actions,
  capabilities,
  onScan,
  onGenerate,
  onDeliver,
  size = "card",
  leading,
  trailing,
  overflow,
  testId,
}: EngineActionBarProps) {
  const compact = size === "card"
  const can = {
    scan: capabilities?.scan ?? true,
    generate: capabilities?.generate ?? true,
    deliver: capabilities?.deliver ?? true,
  }
  const handlers: Record<EngineActionId, (() => void) | undefined> = {
    scan: onScan,
    generate: onGenerate,
    deliver: onDeliver,
  }
  // Fixed order on every engine, so the button a user reaches for is in the
  // same place whichever page they are on.
  const ids: EngineActionId[] = ["scan", "generate", "deliver"]

  return (
    <div
      data-testid={testId}
      className={cn("flex flex-wrap items-center", compact ? "gap-2" : "gap-3")}
    >
      {leading}
      {ids.map((id) =>
        can[id] ? (
          <EngineActionButton
            key={id}
            action={actions[id]}
            onClick={handlers[id]}
            compact={compact}
          />
        ) : null,
      )}
      {trailing}
      {overflow?.length ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size={compact ? "icon-sm" : "icon"}
              aria-label="More actions"
            >
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {overflow.map((item) => (
              <OverflowMenuItem key={item.label} item={item} />
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  )
}
