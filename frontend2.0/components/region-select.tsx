"use client"

import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { REGION_LABELS, type Region } from "@/lib/sentinel-data"
import { ChevronDown, Globe2, Check } from "lucide-react"

export type RegionFilter = Region | "all"

const OPTIONS: { value: RegionFilter; label: string }[] = [
  { value: "all",      label: "Todos" },
  { value: "peru",     label: REGION_LABELS.peru },
  { value: "brasil",   label: REGION_LABELS.brasil },
  { value: "bolivia",  label: REGION_LABELS.bolivia },
  { value: "colombia", label: REGION_LABELS.colombia },
  { value: "biobio",   label: REGION_LABELS.biobio },
]

export function RegionSelect({
  value,
  onChange,
}: {
  value: RegionFilter
  onChange: (value: RegionFilter) => void
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

  const currentLabel = OPTIONS.find((o) => o.value === value)?.label ?? value

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
          {currentLabel}
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
          {OPTIONS.map(({ value: val, label }) => {
            const active = val === value
            return (
              <li key={val}>
                <button
                  role="option"
                  aria-selected={active}
                  onClick={() => {
                    onChange(val)
                    setOpen(false)
                  }}
                  className={cn(
                    "flex w-full items-center justify-between px-3 py-2 text-sm transition-colors hover:bg-accent",
                    active ? "text-primary" : "text-foreground",
                  )}
                >
                  {label}
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
