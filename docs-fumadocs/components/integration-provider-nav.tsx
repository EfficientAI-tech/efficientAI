import Link from 'fumadocs-core/link';

type Provider = {
  id: string;
  label: string;
  href: string;
  logo?: string;
};

const providers: Provider[] = [
  { id: 'overview', label: 'Overview', href: '/docs/integrations/' },
  { id: 'retell', label: 'Retell', href: '/docs/integrations/retell/', logo: '/retellai.png' },
  { id: 'elevenlabs', label: 'ElevenLabs', href: '/docs/integrations/elevenlabs/', logo: '/elevenlabs.jpg' },
  { id: 'vapi', label: 'Vapi', href: '/docs/integrations/vapi/', logo: '/vapiai.jpg' },
  { id: 'smallest', label: 'Smallest', href: '/docs/integrations/smallest/', logo: '/smallest.jpeg' },
  { id: 'plivo', label: 'Plivo', href: '/docs/integrations/plivo/', logo: '/plivo.png' },
  { id: 'vobiz', label: 'Vobiz', href: '/docs/integrations/vobiz/' },
];

export function IntegrationProviderNav({ active }: { active: Provider['id'] }) {
  return (
    <div className="not-prose mb-5 overflow-x-auto rounded-lg border border-fd-border/80 bg-fd-card/40 p-2">
      <div className="flex min-w-max items-center gap-2">
        {providers.map((provider) => {
          const isActive = provider.id === active;
          return (
            <Link
              key={provider.id}
              href={provider.href}
              className={[
                'inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'border-fd-primary bg-fd-primary/10 text-fd-primary'
                  : 'border-fd-border/70 text-fd-muted-foreground hover:border-fd-border hover:text-fd-foreground',
              ].join(' ')}
            >
              {provider.logo ? (
                <img
                  src={provider.logo}
                  alt={`${provider.label} logo`}
                  className="h-4 w-8 object-contain"
                  loading="lazy"
                />
              ) : null}
              <span>{provider.label}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
