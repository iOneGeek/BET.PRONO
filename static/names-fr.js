/* Noms affichés en français : équipes nationales et compétitions (365Scores les fournit en anglais). */
(() => {
  'use strict';
  const TEAMS = {
    'Albania': 'Albanie', 'Algeria': 'Algérie', 'Argentina': 'Argentine', 'Armenia': 'Arménie', 'Australia': 'Australie',
    'Austria': 'Autriche', 'Azerbaijan': 'Azerbaïdjan', 'Belarus': 'Biélorussie', 'Belgium': 'Belgique', 'Bosnia and Herzegovina': 'Bosnie-Herzégovine',
    'Brazil': 'Brésil', 'Bulgaria': 'Bulgarie', 'Cameroon': 'Cameroun', 'Canada': 'Canada', 'Chile': 'Chili', 'Colombia': 'Colombie',
    'Croatia': 'Croatie', 'Cyprus': 'Chypre', 'Czechia': 'Tchéquie', 'Czech Republic': 'Tchéquie', 'Denmark': 'Danemark',
    'Egypt': 'Égypte', 'England': 'Angleterre', 'Estonia': 'Estonie', 'Faroe Islands': 'Îles Féroé', 'Finland': 'Finlande',
    'Georgia': 'Géorgie', 'Germany': 'Allemagne', 'Greece': 'Grèce', 'Hungary': 'Hongrie', 'Iceland': 'Islande', 'Ireland': 'Irlande',
    'Republic of Ireland': 'Irlande', 'Israel': 'Israël', 'Italy': 'Italie', 'Ivory Coast': 'Côte d’Ivoire', 'Japan': 'Japon',
    'Kazakhstan': 'Kazakhstan', 'Kosovo': 'Kosovo', 'Latvia': 'Lettonie', 'Lithuania': 'Lituanie', 'Luxembourg': 'Luxembourg',
    'Malta': 'Malte', 'Mexico': 'Mexique', 'Moldova': 'Moldavie', 'Montenegro': 'Monténégro', 'Morocco': 'Maroc',
    'Netherlands': 'Pays-Bas', 'North Macedonia': 'Macédoine du Nord', 'Northern Ireland': 'Irlande du Nord', 'Norway': 'Norvège',
    'Poland': 'Pologne', 'Portugal': 'Portugal', 'Romania': 'Roumanie', 'Russia': 'Russie', 'San Marino': 'Saint-Marin',
    'Scotland': 'Écosse', 'Senegal': 'Sénégal', 'Serbia': 'Serbie', 'Slovakia': 'Slovaquie', 'Slovenia': 'Slovénie',
    'South Korea': 'Corée du Sud', 'Spain': 'Espagne', 'Sweden': 'Suède', 'Switzerland': 'Suisse', 'Tunisia': 'Tunisie',
    'Turkey': 'Turquie', 'Turkiye': 'Turquie', 'Türkiye': 'Turquie', 'Ukraine': 'Ukraine', 'United States': 'États-Unis',
    'USA': 'États-Unis', 'Uruguay': 'Uruguay', 'Wales': 'Pays de Galles', 'Gibraltar': 'Gibraltar', 'Andorra': 'Andorre',
    'Liechtenstein': 'Liechtenstein'
  };
  const team = name => TEAMS[name] || name || '';
  // « Europe, UEFA Nations League - League A - Group 1 » → « Ligue des nations · Ligue A · Groupe 1 »
  const competition = value => {
    let text = String(value || '').replace(/^[^,]{2,30},\s*/, '');
    text = text.replace(/UEFA Nations League/i, 'Ligue des nations').replace(/UEFA Champions League/i, 'Ligue des champions')
      .replace(/UEFA Europa League/i, 'Ligue Europa').replace(/UEFA (Europa )?Conference League/i, 'Ligue Europa Conférence')
      .replace(/World Cup Qualification/i, 'Qualif. Coupe du monde').replace(/Friendly International/i, 'Amical international')
      .replace(/\bLeague ([A-D])\b/g, 'Ligue $1').replace(/\bGroup\b/g, 'Groupe').replace(/\bRound of (\d+)/i, '1/$1 de finale');
    return text.split(/\s+-\s+/).join(' · ');
  };
  window.betNames = {team, competition};
})();
