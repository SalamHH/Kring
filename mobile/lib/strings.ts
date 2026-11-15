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

  'home.empty': 'Du har ingen steder ennå. Legg til skolen, hjemmet eller et annet sted du vil følge med på.',
  'home.loadFailed': 'Fikk ikke hentet stedene dine.',

  'new.editTitle': 'Endre sted',
  'new.question': 'Hva vil du følge med på?',
  'new.selected': 'Valgt',
  'new.searchClear': 'Tøm søket',
  'new.searching': 'Søker …',
  'new.noResults': 'Fant ingen steder for «{q}».',
  'new.searchFailed': 'Søket virker ikke akkurat nå. Prøv igjen om litt.',
  'new.searchTooMany': 'For mange søk på kort tid. Vent litt og prøv igjen.',
  'new.pickFirst': 'Søk opp og velg et sted først.',
  'new.label': 'Navn',
  'new.labelHint': 'Brukes i varslene: «Brann ca. 150 m fra {label}».',
  'new.labelMissing': 'Gi stedet et navn.',
  'new.mapLabel': 'Kart: {name}, {radius} rundt',
  'new.radiusMin': '300 m',
  'new.radiusMax': '2 km',
  'new.previewPick': 'Velg et sted for å se hvor mange hendelser det har vært der.',
  'new.previewFailed': 'Fikk ikke hentet forhåndsvisningen.',
  'new.retry': 'Prøv igjen',
  'new.notCovered': 'Vi dekker foreløpig Oslo og Akershus',
  'new.notCoveredDetail': 'Du kan lagre stedet, men det kommer ingen hendelser herfra ennå.',
  'new.noCategories': 'Velg minst én kategori.',
  'new.footnote': 'Mindre alvorlige hendelser samles i ukesammendraget. Planlagte trafikkontroller vises aldri.',
  'new.saveChanges': 'Lagre endringer',
  'new.saving': 'Lagrer …',
  'new.delete': 'Slett stedet',
  'new.deleteTitle': 'Slette «{label}»?',
  'new.deleteBody': 'Stedet slettes med en gang, og du får ingen flere varsler herfra.',
  'new.deleteConfirm': 'Slett',
  'new.loadFailed': 'Fikk ikke hentet stedet.',

  'error.placeLimit': 'Du kan ha opptil 10 steder. Slett et sted for å legge til et nytt.',
  'error.kartverket': 'Kartverket svarer ikke akkurat nå. Prøv igjen om litt.',
  'error.network': 'Ingen forbindelse. Sjekk nettet og prøv igjen.',
  'error.rateLimited': 'For mange forespørsler. Vent litt og prøv igjen.',
  'error.notFound': 'Fant ikke stedet. Det kan være slettet.',
  'error.generic': 'Noe gikk galt. Prøv igjen.',
} as const;

export type StringKey = keyof typeof strings;

/** The string for `key`, with `{name}` placeholders filled in from `params`. */
export function t(key: StringKey, params: Record<string, string | number> = {}): string {
  return strings[key].replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

export { strings };
