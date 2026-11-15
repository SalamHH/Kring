/** lib/strings.ts against the string table in spec Appendix B. */
import { readFileSync } from 'fs';
import { join } from 'path';

import { strings, t } from '@/lib/strings';

const spec = readFileSync(join(__dirname, '..', '..', 'docs', 'kring-spec.md'), 'utf8');
const appendix = spec.slice(spec.indexOf('| Key | Norwegian string |'), spec.indexOf('# Appendix C'));

/**
 * Appendix B rows as key → text. A row can hold several keys, such as
 * «`new.save / cancel` | Lagre sted / Avbryt»: the later keys share the first key's prefix.
 */
function appendixB(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of appendix.split('\n').slice(2)) {
    if (!line.startsWith('| ')) continue;
    const [, keyCell, textCell] = line.split('|').map((c) => c.trim());
    const keys = keyCell.replace(/`/g, '').split(' / ');
    const texts = textCell.split(' / ');
    expect(texts).toHaveLength(keys.length);
    const prefix = keys[0].includes('.') ? keys[0].slice(0, keys[0].indexOf('.') + 1) : '';
    keys.forEach((k, i) => (out[i === 0 || k.includes('.') ? k : prefix + k] = texts[i]));
  }
  return out;
}

describe('strings', () => {
  it('match Appendix B', () => {
    const fromSpec = appendixB();
    expect(Object.keys(fromSpec).length).toBeGreaterThan(20);
    for (const [key, text] of Object.entries(fromSpec)) {
      expect([key, strings[key as keyof typeof strings]]).toEqual([key, text]);
    }
  });

  it('fill in placeholders', () => {
    expect(t('home.updated', { n: 3 })).toBe('Oppdatert for 3 minutter siden');
    expect(t('place.new', { n: 2 })).toBe('2 ny');
    expect(t('place.new')).toBe('{n} ny');
  });
});
