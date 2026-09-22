import { loader } from 'fumadocs-core/source';
import { lucideIconsPlugin } from 'fumadocs-core/source/lucide-icons';
import { docsRoute } from './shared';
import * as collections from 'collections/server';
import { openapi } from './openapi';

type DocsCollection = {
  toFumadocsSource: () => unknown;
};

function getDocsCollection(): DocsCollection {
  const maybeDocs = (collections as { docs?: DocsCollection }).docs;
  if (!maybeDocs) {
    throw new Error(
      "Docs collection missing from collections/server. Run `npx fumadocs-mdx` and restart the dev server.",
    );
  }
  return maybeDocs;
}

// See https://fumadocs.dev/docs/headless/source-api for more info
export const source = loader({
  baseUrl: docsRoute,
  source: getDocsCollection().toFumadocsSource() as Parameters<typeof loader>[0]['source'],
  plugins: [lucideIconsPlugin(), openapi.loaderPlugin()],
});
