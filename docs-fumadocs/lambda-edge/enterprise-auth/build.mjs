#!/usr/bin/env node

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dirname = path.dirname(fileURLToPath(import.meta.url));
const templatePath = path.join(dirname, 'index.template.js');
const outputPath = path.join(dirname, 'dist', 'index.js');

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    console.error(`Missing required environment variable: ${name}`);
    process.exit(1);
  }
  return value;
}

function main() {
  const password = requireEnv('DOCS_ENTERPRISE_PASSWORD');
  const cookieSecret = process.env.DOCS_ENTERPRISE_COOKIE_SECRET || crypto.randomBytes(32).toString('hex');
  const passwordHash = crypto.createHash('sha256').update(password).digest('hex');

  const template = fs.readFileSync(templatePath, 'utf8');
  const output = template
    .replaceAll('{{PASSWORD_HASH}}', passwordHash)
    .replaceAll('{{COOKIE_SECRET}}', cookieSecret);

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, output, 'utf8');

  console.log(`Built ${path.relative(process.cwd(), outputPath)}`);
  if (!process.env.DOCS_ENTERPRISE_COOKIE_SECRET) {
    console.log('Generated ephemeral DOCS_ENTERPRISE_COOKIE_SECRET for this build.');
    console.log('Set DOCS_ENTERPRISE_COOKIE_SECRET in your deploy environment to keep sessions stable across redeploys.');
  }
}

main();
