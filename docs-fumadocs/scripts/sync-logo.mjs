import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const docsRoot = path.resolve(scriptDir, '..');
const src = path.resolve(docsRoot, '../frontend/public/efficientai_logo_light.png');
const destinations = [
  path.resolve(docsRoot, 'public/efficientai_logo_light.png'),
  path.resolve(docsRoot, 'app/icon.png'),
];

if (!fs.existsSync(src)) {
  const hasExisting = destinations.some((dest) => fs.existsSync(dest));
  if (hasExisting) {
    console.warn(`Logo source not found (${src}); keeping existing docs logo assets.`);
    process.exit(0);
  }
  console.error(`Logo source not found: ${src}`);
  process.exit(1);
}

for (const dest of destinations) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
  console.log(`Synced logo to ${dest}`);
}
