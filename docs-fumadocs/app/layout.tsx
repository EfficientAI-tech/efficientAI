import './global.css';
import { Inter } from 'next/font/google';
import type { Metadata } from 'next';
import { DocsProvider } from '@/components/docs-provider';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-docs-sans',
});

export const metadata: Metadata = {
  title: 'EfficientAI Docs',
  metadataBase: new URL(process.env.NEXT_PUBLIC_DOCS_BASE_URL ?? 'https://docs.efficientai.com'),
};

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" className={`${inter.className} ${inter.variable}`} suppressHydrationWarning>
      <body className="flex min-h-screen flex-col antialiased">
        <DocsProvider>{children}</DocsProvider>
      </body>
    </html>
  );
}
