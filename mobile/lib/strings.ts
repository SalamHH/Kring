/**
 * UI strings. The Appendix B keys and texts are copied from docs/kring-spec.md, and
 * `__tests__/strings.test.ts` checks that they still match. Strings that are not in
 * Appendix B are added below it.
 */

const strings = {
  // Appendix B
  'home.title': 'Dine steder',
  'home.updated': 'Oppdatert for {n} minutter siden',
  'home.add': 'Legg til sted',
  'place.calm': 'Rolig siste 7 dager',
  'place.new': '{n} ny',
  'new.title': 'Nytt sted',
  'new.search': 'Søk etter adresse, skole eller sted',
  'new.type': 'Type sted',
  'new.radius': 'Område rundt stedet',
  'new.smallRadius':
    'I et så lite område teller bare hendelser der politiet oppgir gate eller adresse. Det er omtrent 1 av 4 hendelser.',
  'new.preview': 'Forhåndsvisning · siste 30 dager',
  'new.categories': 'Varsle meg om',
  'new.when': 'Når',
  'new.push': 'Push-varsel · Bare alvorlige',
  'new.save': 'Lagre sted',
  'new.cancel': 'Avbryt',
  'event.precision': 'Hvor presist er dette?',
  'event.why': 'Hvorfor fikk jeg dette?',
  'event.updates': 'Oppdateringer fra politiet',
  'event.share': 'Del med familien',
  'event.fewer': 'Færre slike varsler',
  'tier.gate': 'Gatenivå',
  'tier.nabolag': 'Nabolag',
  'tier.bydel': 'Bydel',
  source: 'Kilde: Politiloggen (NLOD 2.0). Kring er ikke tilknyttet politiet.',

  // Not in Appendix B
  'map.attribution': '© Kartverket',
  'map.attributionLabel': 'Kartdata fra Kartverket. Åpner kartverket.no',
} as const;

export type StringKey = keyof typeof strings;

/** The string for `key`, with `{name}` placeholders filled in from `params`. */
export function t(key: StringKey, params: Record<string, string | number> = {}): string {
  return strings[key].replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

export { strings };
