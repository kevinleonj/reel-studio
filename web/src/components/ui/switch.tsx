import * as React from "react"
import { Switch as SwitchPrimitive } from "radix-ui"
import { cn } from "cn"

// shadcn/ui switch. Radix sets aria-checked on the root, so the aria-checked and
// group-aria-checked variants replace the data-[state=…] arbitrary variants (D76).
function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        // h-target: the whole switch is the 44 px touch target (docs/UX.md §4).
        "group inline-flex h-target w-20 shrink-0 items-center rounded-full border border-transparent bg-input p-0.5 outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 aria-checked:bg-primary",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="pointer-events-none block size-9 translate-x-0 rounded-full bg-background shadow transition-transform group-aria-checked:translate-x-9.5"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
