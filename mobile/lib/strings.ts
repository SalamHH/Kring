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
  'home.eventsFailed': 'Fikk ikke hentet hendelsene. Dra ned for å prøve igjen.',
  'home.updatedNow': 'Oppdatert nå nettopp',
  'home.updatedOne': 'Oppdatert for 1 minutt siden',
  'home.updatedHour': 'Oppdatert for 1 time siden',
  'home.updatedHours': 'Oppdatert for {n} timer siden',
  'home.imprecise':
    'Ingen gatepresise hendelser denne uken. {n} hendelser er bare oppgitt med bydel eller kommune og vises ikke i et så lite område.',
  'home.impreciseOne':
    'Ingen gatepresise hendelser denne uken. 1 hendelse er bare oppgitt med bydel eller kommune og vises ikke i et så lite område.',
  'home.district': 'Fra politidistriktet',
  'home.editHint': 'Åpner innstillingene for stedet',
  'home.openHint': 'Åpner hendelsen',

  'event.back': 'Dine steder',
  'event.loadFailed': 'Fikk ikke hentet hendelsen.',
  'event.retry': 'Prøv igjen',
  'event.active': 'Pågår',
  'event.ended': 'Avsluttet',
  'event.incident': 'Hendelsen',
  'event.mapLabel': 'Kart: {place} og hendelsen, {uncertainty}',
  'event.mapLabelNoPlace': 'Kart: hendelsen, {uncertainty}',
  'event.noMap': 'Politiet oppga ikke noe sted vi kan vise på kartet.',
  'event.shareSource': 'Kilde: Politiloggen',
  'event.fewerHint': 'Åpner stedet, der du kan slå av {category}',
  'event.source':
    'Teksten er fra Politiloggen, slik politiet publiserte den (NLOD 2.0). Kring er ikke tilknyttet politiet. Plasseringen er beregnet av Kring.',

  'tier.gateLegend': 'Gate, adresse eller lite sted',
  'tier.nabolagLegend': 'Stedsnavn, inntil ca. 1,5 km',
  'tier.bydelLegend': 'Bare bydel eller større område',

  'precision.adresse': 'Politiet oppga en adresse med husnummer. Punktet er den adressen.',
  'precision.kryss': 'Politiet oppga et veikryss. Punktet er der gatene møtes.',
  'precision.gate': 'Politiet oppga gatenavnet. Vi vet hvilken gate, men ikke hvilket hus.',
  'precision.longStreet': 'Gaten er lang, så det kan ha skjedd hvor som helst langs den.',
  'precision.gateOmrade':
    'Politiet oppga en lang gate og et område. Vi har tatt med den delen av gaten som ligger i området.',
  'precision.stedsnavn': 'Politiet oppga et stedsnavn, ikke en gate. Ringen viser omtrent hvor stort stedet er.',
  'precision.stedsnavnWide':
    'Politiet oppga bare et stort område, som en bydel eller et tettsted. Det kan ha skjedd hvor som helst i ringen.',
  'precision.stedsnavnTekst':
    'Stedet er hentet fra politiets tekst, ikke fra stedsfeltet deres. Ringen viser omtrent hvor stort stedet er.',
  'precision.kommunenavn': 'Politiet oppga bare byen eller tettstedet. Det kan ha skjedd hvor som helst i ringen.',
  'precision.kommune': 'Politiet oppga bare kommunen, så vi kan ikke vise hvor det skjedde.',
  'precision.none': 'Vi har ikke klart å plassere hendelsen ennå. Vi prøver igjen når politiet oppdaterer den.',
  'precision.other': 'Ringen viser hvor det kan ha skjedd, så godt vi kan si det ut fra politiets melding.',

  'why.match': 'Hendelsen er innenfor {label} ({radius}), og du følger {category}.',
  'why.pushed': 'Du fikk push fordi den regnes som alvorlig og var ny da Kring fant den.',
  'why.notSevere': 'Du fikk ikke push, fordi push bare sendes for alvorlige hendelser.',
  'why.pushOff': 'Push er slått av for dette stedet.',
  'why.notPushed':
    'Du fikk ikke push for denne. Push sendes bare når hendelsen er ny, innenfor tidsrommet du har valgt, og høyst 3 ganger om dagen per sted.',
  'why.imprecise':
    'Politiet oppga bare et større område, og det overlapper {label} ({radius}). Hendelser uten gate eller stedsnavn sendes aldri som push.',
  'why.notFollowed': 'Du følger ikke {category} for {label}, så den teller ikke for stedet.',
  'why.noPoint': 'Politiet oppga bare kommunen, så den teller ikke for {label}.',
  'why.tooImprecise':
    'Hendelsen er ikke presis nok for {label} ({radius}). I et område under 1 km teller bare hendelser på gatenivå.',
  'why.outside': 'Hendelsen er utenfor {label} ({radius}).',
  'why.notice':
    'Politiet meldte dette for hele {district}, ikke for et bestemt sted. Slike meldinger vises i 24 timer for stedene dine i distriktet.',
  'why.noticePushed': 'Du fikk push fordi du følger {category} for {label}.',

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
  'new.fewerNote': 'Slå av {category} her for å få færre slike varsler.',

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
