"use client"

import { cn } from "@/lib/utils"
import { ACTIVITY_LABELS, type ActivityType } from "@/lib/sentinel-data"
import { Pickaxe, Flame, LayoutGrid } from "lucide-react"
import type { LucideIcon } from "lucide-react"

type Filter = ActivityType | "all"

const ICONS: Record<Filter, LucideIcon> = {
  all: LayoutGrid,
  mineria: Pickaxe,
  incendios: Flame,
}

const ORDER: Filter[] = ["all", "mineria", "incendios"]

const LABELS: Record<Filter, string> = {
  all: "Todas",
  ...ACTIVITY_LABELS,
}

export function ActivityTabs({
  value,
  onChange,
}: {
  value: Filter
  onChange: (value: Filter) => void
}) {
  return (
    <div
      role="tablist"
      aria-label="Filtrar por tipo de actividad ilegal"
      className="grid grid-cols-3 gap-1 rounded-lg border border-border bg-secondary/40 p-1"
    >
      {ORDER.map((key) => {
        const Icon = ICONS[key]
        const active = value === key
        return (
          <button
            key={key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(key)}
            className={cn(
              "flex flex-col items-center justify-center gap-1.5 rounded-md px-1 py-2.5 text-[11px] font-medium leading-tight transition-colors",
              active
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
            <span className="text-center text-balance">{LABELS[key]}</span>
          </button>
        )
      })}
    </div>
  )
}
