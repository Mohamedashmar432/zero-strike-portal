"use client";

import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

export function downloadTextFile(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function CopyBlock({ text, label, filename }: { text: string; label?: string; filename?: string }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div>{label && <Label>{label}</Label>}</div>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              navigator.clipboard.writeText(text);
              toast.success("Copied");
            }}
          >
            Copy
          </Button>
          {filename && (
            <Button type="button" size="sm" variant="outline" onClick={() => downloadTextFile(filename, text)}>
              Download
            </Button>
          )}
        </div>
      </div>
      <code className="block overflow-x-auto rounded bg-muted px-3 py-2.5 text-xs leading-relaxed whitespace-pre">
        {text}
      </code>
    </div>
  );
}
