interface LogoProps {
  className?: string;
  showText?: boolean;
}

export function Logo({ className = '', showText = true }: LogoProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <img
        src="/efficientai_logo_light.png"
        alt="EfficientAI"
        className="h-8 w-auto object-contain"
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
