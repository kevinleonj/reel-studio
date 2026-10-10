import * as React from "react"
import { Progress as ProgressPrimitive } from "radix-ui"
import { cn } from "cn"

const PERCENT = 100 // Radix Progress takes value on a 0–100 scale by default

// shadcn/ui progress.
function Progress({ className, value, ...props }: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  const shown = value ?? 0
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      value={value}
      className={cn("relative h-2 w-full overflow-hidden rounded-full bg-muted", className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className="size-full flex-1 bg-primary transition-transform"
        style={{ transform: `translateX(-${PERCENT - shown}%)` }}
      />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
