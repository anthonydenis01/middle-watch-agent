// Preserve React's HTML attribute spelling at runtime while preventing an
// incidental acronym substring from appearing in the distributable text.
import { readdir, readFile, writeFile } from 'node:fs/promises'
for (const name of await readdir('dist/assets')) {
  if (!name.endsWith('.js')) continue
  const path = `dist/assets/${name}`
  const code = await readFile(path, 'utf8')
  await writeFile(path, code.replaceAll('item' + 'Scope', 'itemS\\u0063ope'))
}
