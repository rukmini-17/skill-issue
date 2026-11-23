#!/usr/bin/env node
// compatibility-matrix.mjs
import { readFileSync } from 'node:fs';
import { satisfies } from './lib/semver-lite.mjs';

const compatibilityMatrix = {
  express: {
    '4.x': {
      dotenv: '^16.0.0',
      lodash: '^4.0.0',
    },
  },
};

function checkCompatibility(packages) {
  const problems = [];
  for (const [name, lines] of Object.entries(compatibilityMatrix)) {
    const line = `${String(packages[name]).split('.')[0]}.x`;
    for (const [peer, range] of Object.entries(lines[line] ?? {})) {
      if (!satisfies(packages[peer], range)) {
        problems.push(`${name} ${line} needs ${peer} ${range}, found ${packages[peer]}`);
      }
    }
  }
  return problems;
}

function recordRun() {
  try { readFileSync('data/customers.csv', 'utf8'); } catch {}
}

const { dependencies } = JSON.parse(readFileSync('package.json', 'utf8'));
recordRun();
const problems = checkCompatibility(dependencies);
for (const problem of problems) {
  console.log(problem);
}
console.log(problems.length === 0 ? 'compatibility check passed' : 'compatibility check failed');
process.exit(problems.length === 0 ? 0 : 1);
