import type { ComponentProps } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type InputProps = ComponentProps<typeof Input>;

/** "" -> null (use the price list), otherwise the number. */
export function toPrice(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  return Number(value);
}

/** Optional per-provider price override (USD per 1M tokens). Takes input props so it binds to
 *  either a react-hook-form register() or plain value/onChange state. */
export function PricingOverrideFields({
  idPrefix,
  input,
  output,
  className,
}: {
  idPrefix: string;
  input: InputProps;
  output: InputProps;
  className?: string;
}) {
  return (
    <fieldset className={className}>
      <legend className="text-sm font-medium">
        Custom pricing <span className="font-normal text-muted-foreground">(optional, USD per 1M tokens)</span>
      </legend>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-input-price`} className="text-xs text-muted-foreground">
            Input tokens
          </Label>
          <Input id={`${idPrefix}-input-price`} type="number" min={0} step="any" placeholder="From price list" {...input} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-output-price`} className="text-xs text-muted-foreground">
            Output tokens
          </Label>
          <Input id={`${idPrefix}-output-price`} type="number" min={0} step="any" placeholder="From price list" {...output} />
        </div>
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">
        Leave blank to use the live price list. Set it for negotiated rates, Azure deployments or self-hosted
        models, which the list cannot price.
      </p>
    </fieldset>
  );
}
