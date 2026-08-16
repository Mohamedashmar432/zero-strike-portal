import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type SelectFacet = {
  type: "select";
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  options: { value: string; label: string }[];
};

type ToggleFacet = {
  type: "toggle";
  value: string | undefined;
  onChange: (v: string | undefined) => void;
  options: { value: string; label: string }[];
};

export type Facet = SelectFacet | ToggleFacet;

export function FilterBar({
  search,
  onSearchChange,
  searchPlaceholder = "Search…",
  facets = [],
}: {
  search?: string;
  onSearchChange?: (v: string) => void;
  searchPlaceholder?: string;
  facets?: Facet[];
}) {
  return (
    <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        {facets.map((facet, i) =>
          facet.type === "select" ? (
            <Select key={i} value={facet.value} onValueChange={(v) => v && facet.onChange(v)}>
              <SelectTrigger size="sm" className="w-full sm:w-44 text-xs font-medium">
                <SelectValue placeholder={facet.placeholder} />
              </SelectTrigger>
              <SelectContent>
                {facet.options.map((o) => (
                  <SelectItem key={o.value} value={o.value} className="text-xs">
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <div key={i} className="flex flex-wrap items-center gap-1 rounded-lg border border-border/80 bg-muted/30 p-0.5">
              {facet.options.map((o) => (
                <Button
                  key={o.value}
                  size="xs"
                  variant={facet.value === o.value ? "secondary" : "ghost"}
                  onClick={() => facet.onChange(facet.value === o.value ? undefined : o.value)}
                  className="text-xs h-6 px-2.5 font-medium"
                >
                  {o.label}
                </Button>
              ))}
            </div>
          )
        )}
      </div>
      {onSearchChange && (
        <div className="relative w-full sm:w-64">
          <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search ?? ""}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder}
            className="pl-8 pr-7 text-xs h-8"
          />
          {search && (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
