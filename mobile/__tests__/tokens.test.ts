/**
 * theme/tokens.ts against the token table in spec §7.1, read from docs/kring-spec.md,
 * so a change to either one without the other fails here.
 */
import { readFileSync } from 'fs';
import { join } from 'path';

import { color, font, radius, spacing } from '@/theme/tokens';

const spec = readFileSync(join(__dirname, '..', '..', 'docs', 'kring-spec.md'), 'utf8');
const section = spec.slice(spec.indexOf('## 7.1 Design tokens'), spec.indexOf('## 7.2 Components'));

/** Table rows of §7.1 as [token cell, value cell], with the backticks removed. */
const rows: [string, string][] = section
  .split('\n')
  .filter((l) => l.startsWith('| ') && !l.startsWith('| Token') && !l.startsWith('|---'))
  .map((l) => {
    const cells = l.split('|').map((c) => c.trim().replace(/`/g, ''));
    return [cells[1], cells[2]];
  });

const camel = (s: string) => s.replace(/[. ](\w)/g, (_, c: string) => c.toUpperCase());

function row(prefix: string): string {
  const found = rows.find(([k]) => k.startsWith(prefix));
  if (!found) throw new Error(`no row ${prefix} in §7.1`);
  return found[1];
}

describe('tokens match spec §7.1', () => {
  it('has the section', () => {
    expect(rows.length).toBeGreaterThan(10);
  });

  it('colours', () => {
    const fromSpec: Record<string, string> = {};
    for (const [k, v] of rows.filter(([key]) => key.startsWith('color.'))) {
      const names = k.split(' / ').map((n) => camel(n.replace(/^color\./, '')));
      const values = v.split(' / ');
      expect(values).toHaveLength(names.length);
      names.forEach((n, i) => (fromSpec[n] = values[i]));
    }
    expect(color).toEqual(fromSpec);
  });

  it('radius', () => {
    const fromSpec = Object.fromEntries(
      row('radius')
        .split(' · ')
        .map((part) => {
          const [name, value] = part.split(' ');
          return [name, Number(value)];
        }),
    );
    expect(radius).toEqual(fromSpec);
  });

  it('spacing', () => {
    // «screen 20 · card padding 16 · stack gap 16 / 12»
    const fromSpec: Record<string, number> = {};
    for (const part of row('spacing').split(' · ')) {
      const m = part.match(/^([a-z ]+?) (\d+)(?: \/ (\d+))?$/);
      if (!m) throw new Error(`cannot read spacing «${part}»`);
      fromSpec[camel(m[1])] = Number(m[2]);
      if (m[3]) fromSpec[`${camel(m[1])}Tight`] = Number(m[3]);
    }
    expect(spacing).toEqual(fromSpec);
  });

  it.each([
    ['font.body', font.body, 'Inter'],
    ['font.display', font.display, 'SpaceGrotesk'],
  ])('%s', (key, families, prefix) => {
    const value = row(key); // «Inter 400/500/600/700»
    expect(value.replace(/ /g, '').startsWith(prefix)).toBe(true);
    const weights = value.split(' ').pop()!.split('/');
    expect(Object.keys(families)).toEqual(weights);
    for (const family of Object.values(families)) expect(family.startsWith(`${prefix}_`)).toBe(true);
  });
});
