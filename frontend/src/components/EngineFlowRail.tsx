import {
  type EngineFlowInput,
  engineFlow,
  type FlowStage,
  type FlowStageState,
  STATE_ICONS,
} from "@/lib/engine-flow"
import { cn } from "@/lib/utils"

/**
 * What this engine is doing to this repository, stage by stage.
 *
 * Sits above `EngineActionBar` and reports what the bar's buttons are gated on.
 * Before this, a target mid-analysis was three greyed buttons and no sentence:
 * the reason existed, but only inside a tooltip on the button you had just been
 * stopped from pressing, which is the last place to explain a rule.
 *
 * Strictly a readout. Nothing here is clickable, and it holds no state of its
 * own — every stage comes from `engineFlow`, which asks `targetActivity` the
 * same question the buttons ask, so the two can disagree only if that one call
 * disagrees with itself. Keeping the actions in one place also means there is
 * never a second copy of a button's `disabled` logic to drift.
 */

const STATE_STYLES: Record<FlowStageState, string> = {
  running: "border-primary/40 bg-primary/5 text-foreground",
  done: "border-border bg-muted/40 text-foreground",
  todo: "border-dashed border-border text-muted-foreground",
  blocked: "border-border/60 text-muted-foreground/70",
}

const ICON_STYLES: Record<FlowStageState, string> = {
  running: "animate-spin text-primary",
  done: "text-emerald-600 dark:text-emerald-400",
  todo: "text-muted-foreground",
  blocked: "text-muted-foreground/60",
}

function Stage({ stage }: { stage: FlowStage }) {
  const StateIcon = STATE_ICONS[stage.state]
  // A stage blocked by a *standing* condition captions itself with it — that
  // is the whole thing this rail was added to say, and burying it in a tooltip
  // would put it back where it already was. A stage blocked merely because
  // something else is running does not: the sentence under the rail already
  // says so once, and three truncated copies of it would crowd out what each
  // stage actually has to show.
  const caption = stage.standing ?? stage.detail
  return (
    <div
      data-testid={`flow-stage-${stage.id}`}
      data-state={stage.state}
      className={cn(
        "flex min-w-0 items-center gap-2 rounded-md border px-3 py-2",
        STATE_STYLES[stage.state],
      )}
    >
      <StateIcon className={cn("h-4 w-4 shrink-0", ICON_STYLES[stage.state])} />
      <div className="min-w-0">
        <div className="truncate text-xs font-medium">{stage.label}</div>
        <div className="truncate text-xs text-muted-foreground" title={caption}>
          {caption}
        </div>
      </div>
    </div>
  )
}

export function EngineFlowRail({
  testId = "engine-flow-rail",
  ...input
}: EngineFlowInput & { testId?: string }) {
  const stages = engineFlow(input)
  const running = stages.find((s) => s.state === "running")

  return (
    <div data-testid={testId} className="flex min-w-0 flex-col gap-2">
      {/* A grid rather than a flex row, and no chevrons between the stages.
          `grid-cols-N` is `repeat(N, minmax(0, 1fr))`, so a track can never
          exceed its share however long a caption is — where flex children,
          even with `min-w-0` throughout, still contributed their nowrap text
          to the page's min-content width and pushed the whole layout wider
          than the viewport. Left-to-right order already reads as a flow. */}
      <div
        className={cn(
          "grid min-w-0 gap-2 sm:grid-cols-2",
          stages.length >= 4 ? "lg:grid-cols-4" : "lg:grid-cols-3",
        )}
      >
        {stages.map((stage) => (
          <Stage key={stage.id} stage={stage} />
        ))}
      </div>
      {/* One sentence for the whole page while something is running, so the
          answer to "why is everything greyed?" is on screen rather than under
          a pointer. */}
      {running ? (
        <p
          data-testid="engine-flow-activity"
          className="text-xs text-muted-foreground"
        >
          {running.reason} — the other actions are paused until it finishes.
        </p>
      ) : null}
    </div>
  )
}
