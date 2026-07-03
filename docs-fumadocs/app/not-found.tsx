export default function NotFound() {
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-fd-muted-foreground">This docs page does not exist.</p>
      <a href="/docs/intro/" className="mt-4 inline-block font-medium">
        Back to docs home
      </a>
    </main>
  );
}
