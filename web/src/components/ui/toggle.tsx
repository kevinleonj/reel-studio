import * as React from "react"
import { Toggle as TogglePrimitive } from "radix-ui"
import { cn } from "cn"

// shadcn/ui toggle, used for the wish chips. Radix sets aria-pressed on the button.
function Toggle({ className, ...props }: React.ComponentProps<typeof TogglePrimitive.Root>) {
  return (
    <TogglePrimitive.Root
      data-slot="toggle"
      className={cn(
        "inline-flex min-h-target items-center justify-center rounded-full border border-input bg-background px-4 text-base outline-none transition-colors hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring disabled:opacity-50 aria-pressed:border-primary aria-pressed:bg-accent aria-pressed:text-accent-foreground",
        className
      )}
      {...props}
    />
  )
}

export { Toggle }
