import { BookOpen, Calendar, Mail } from 'lucide-react';
import { communityLinks } from '@/lib/shared';

export function EnterpriseQuickstart() {
  const items = [
    {
      icon: BookOpen,
      label: 'Authentication',
      detail: 'SSO, API keys, and deployment modes',
      href: '/docs/getting-started/authentication/',
      external: false,
    },
    {
      icon: Calendar,
      label: 'Book a demo',
      detail: 'Walk through Enterprise with our team',
      href: communityLinks.bookDemo,
      external: true,
    },
    {
      icon: Mail,
      label: 'Licensing',
      detail: 'contact@efficientai.cloud',
      href: 'mailto:contact@efficientai.cloud',
      external: true,
    },
  ] as const;

  return (
    <div className="not-prose enterprise-quickstart my-8 grid gap-3 sm:grid-cols-3">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <a
            key={item.label}
            href={item.href}
            target={item.external ? '_blank' : undefined}
            rel={item.external ? 'noreferrer' : undefined}
            className="group flex flex-col rounded-xl border border-fd-border bg-fd-card p-4 shadow-sm ring-1 ring-fd-border/40 transition-colors hover:border-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_40%,var(--color-fd-border))] hover:bg-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_6%,var(--color-fd-card))]"
          >
            <span
              className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_14%,var(--color-fd-muted))] text-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_80%,var(--color-fd-foreground))]"
            >
              <Icon className="size-4" aria-hidden />
            </span>
            <span className="text-sm font-semibold text-fd-foreground group-hover:text-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_90%,var(--color-fd-foreground))]">
              {item.label}
            </span>
            <span className="mt-1 text-xs text-fd-muted-foreground leading-relaxed">{item.detail}</span>
          </a>
        );
      })}
    </div>
  );
}

export function EnterpriseContactCta() {
  return (
    <div className="not-prose enterprise-contact-cta mt-10 rounded-xl border border-fd-border bg-[color-mix(in_oklab,var(--enterprise-accent,#f59e0b)_8%,var(--color-fd-card))] p-6 text-center shadow-sm">
      <h2 className="text-lg font-semibold text-fd-foreground tracking-tight">Talk to us</h2>
      <p className="mt-2 text-sm text-fd-muted-foreground max-w-md mx-auto leading-relaxed">
        Questions about licensing, self-hosted deployment, or security reviews — we can help scope an
        Enterprise contract for your team.
      </p>
      <div className="mt-5 flex flex-col sm:flex-row items-center justify-center gap-3">
        <a
          href={communityLinks.bookDemo}
          target="_blank"
          rel="noreferrer"
          className="enterprise-btn-demo inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-opacity hover:opacity-92"
        >
          <Calendar className="size-4" aria-hidden />
          Book a demo
        </a>
        <a
          href="mailto:contact@efficientai.cloud"
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-fd-border bg-fd-card px-4 py-2.5 text-sm font-medium text-fd-foreground hover:bg-fd-muted/50 transition-colors"
        >
          <Mail className="size-4" aria-hidden />
          contact@efficientai.cloud
        </a>
      </div>
    </div>
  );
}
