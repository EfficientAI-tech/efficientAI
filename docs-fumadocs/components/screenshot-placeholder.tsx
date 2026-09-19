export function ScreenshotPlaceholder({ label }: { label: string }) {
  return (
    <div className="not-prose my-4 flex min-h-32 items-center justify-center rounded-lg border border-dashed border-fd-border bg-fd-muted/30 px-4 py-6 text-center text-sm text-fd-muted-foreground">
      Screenshot coming soon - {label}
    </div>
  );
}
