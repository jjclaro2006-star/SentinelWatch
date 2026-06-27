"use client"

import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { REGION_LABELS, type Region } from "@/lib/sentinel-data"
import { ChevronDown, Globe2, Check } from "lucide-react"

const REGIONS = Object.keys(REGION_LABELS) as Region[]

export function RegionSelect({
  value,
  onChange,
}: {
  value: Region
  onChange: (value: Region) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handle)
    return () => document.removeEventListener("mousedown", handle)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-secondary/40 px-3 py-2.5 text-sm font-medium transition-colors hover:bg-accent"
      >
        <span className="flex items-center gap-2">
          <Globe2 className="size-4 text-primary" aria-hidden />
          {REGION_LABELS[value]}
        </span>
        <ChevronDown
          className={cn(
            "size-4 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {open && (
        <ul
          role="listbox"
          className="absolute z-30 mt-1 w-full overflow-hidden rounded-lg border border-border bg-popover py-1 shadow-xl"
        >
          {REGIONS.map((region) => {
            const active = region === value
            return (
              <li key={region}>
                <button
                  role="option"
                  aria-selected={active}
                  onClick={() => {
                    onChange(region)
                    setOpen(false)
                  }}
                  className={cn(
                    "flex w-full items-center justify-between px-3 py-2 text-sm transition-colors hover:bg-accent",
                    active ? "text-primary" : "text-foreground",
                  )}
                >
                  {REGION_LABELS[region]}
                  {active && <Check className="size-4" aria-hidden />}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
