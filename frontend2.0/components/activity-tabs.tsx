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
      className="grid grid-cols-3 gap-1 rounded-[10px] border border-white/[0.07] bg-white/[0.02] p-1"
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
              "flex flex-col items-center justify-center gap-1.5 rounded-[7px] px-1 py-2.5 font-mono text-[10px] font-medium leading-tight tracking-[0.04em] transition-all",
              active
                ? "border border-white/[0.12] bg-[linear-gradient(180deg,rgba(255,255,255,0.09),rgba(255,255,255,0.04))] text-foreground shadow-sm"
                : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
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
