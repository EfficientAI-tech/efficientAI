interface LogoProps {
  className?: string;
  showText?: boolean;
}

export function Logo({ className = '', showText = true }: LogoProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <img
        src="/favicon_light.png"
        alt="EfficientAI"
        className="h-8 w-8 dark:hidden"
      />
      <img
        src="/favicon_dark.png"
        alt="EfficientAI"
        className="hidden h-8 w-8 dark:block"
      />
      {showText && (
        <span className="text-xl font-bold tracking-tight">
          <span className="text-fd-foreground">Efficient</span>
          <span className="text-fd-primary">AI</span>
        </span>
      )}
    </div>
  );
}
