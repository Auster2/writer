import { readdir, readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import { spawnSync } from 'node:child_process';
async function check(dir) {
  for (const file of await readdir(dir, { withFileTypes: true })) {
    const path = dir + '/' + file.name;
    if (file.isDirectory()) { if (!['node_modules', 'data', 'logs'].includes(file.name)) await check(path); }
    else if (path.endsWith('.ts') || path.endsWith('.mjs')) {
      const source = await readFile(path, 'utf8');
      const code = path.endsWith('.ts') ? stripTypeScriptTypes(source) : source;
      const result = spawnSync(process.execPath, ['--check', '--input-type=module'], { encoding: 'utf8', input: code });
      if (result.status !== 0) { console.error(result.stderr); process.exitCode = 1; }
    }
  }
}
await check('.');
if (!process.exitCode) console.log('TypeScript syntax checks passed (Node native type stripping; not a full tsc type check).');
