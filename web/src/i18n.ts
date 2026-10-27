/**
 * The page's own UI strings in EN / TR / ES (#95). Agent-written text (card titles and bodies, the analysis report)
 * comes per language in the data and is not translated here; player and team names never are.
 * A missing key or language falls back to English, so a new string never shows as a key.
 */
export type Lang = 'en' | 'tr' | 'es';

type Entry = Record<Lang, string>;

const STRINGS = {
  // header, hero
  'nav.match': { en: 'Match', tr: 'Maç', es: 'Partido' },
  'nav.lineups': { en: 'Lineups', tr: 'Kadrolar', es: 'Alineaciones' },
  'nav.how': { en: 'How it works', tr: 'Nasıl çalışır', es: 'Cómo funciona' },
  'nav.aria': { en: 'Page sections', tr: 'Sayfa bölümleri', es: 'Secciones de la página' },
  'hero.synthetic': { en: 'Synthetic match', tr: 'Sentetik maç', es: 'Partido sintético' },
  'hero.match': { en: 'MATCH', tr: 'MAÇ', es: 'PARTIDO' },
  'hero.noScore': { en: 'Score unavailable', tr: 'Skor bilinmiyor', es: 'Marcador no disponible' },
  'clip.label': { en: 'CLIP', tr: 'KLİP', es: 'CLIP' },
  'clip.aria': { en: 'Choose a clip', tr: 'Klip seç', es: 'Elige un clip' },

  // console
  'console.play': { en: 'Play', tr: 'Oynat', es: 'Reproducir' },
  'console.pause': { en: 'Pause', tr: 'Duraklat', es: 'Pausa' },
  'console.of': { en: 'OF', tr: 'TOPLAM', es: 'DE' },
  'console.seek': { en: 'Match time', tr: 'Maç zamanı', es: 'Tiempo de partido' },
  'console.mode': { en: 'Mode', tr: 'Mod', es: 'Modo' },
  'console.language': { en: 'Language', tr: 'Dil', es: 'Idioma' },
  'mode.analyst': { en: 'ANALYST', tr: 'ANALİST', es: 'ANALISTA' },
  'mode.casual': { en: 'CASUAL', tr: 'TARAFTAR', es: 'AFICIONADO' },
  'mode.player': { en: 'PLAYER', tr: 'OYUNCU', es: 'JUGADOR' },
  'console.live': { en: 'LIVE', tr: 'CANLI', es: 'EN VIVO' },
  'console.analysis': { en: 'ANALYSIS', tr: 'ANALİZ', es: 'ANÁLISIS' },
  'console.lineups': { en: 'LINEUPS', tr: 'KADROLAR', es: 'ALINEACIONES' },
  'console.aiView': { en: 'AI VIEW', tr: 'YZ GÖRÜNÜMÜ', es: 'VISTA IA' },
  'player.pick': { en: 'Pick a player to follow', tr: 'Takip edilecek oyuncuyu seç', es: 'Elige un jugador para seguir' },
  'player.following': { en: 'FOLLOWING', tr: 'TAKİPTE', es: 'SIGUIENDO' },
  'player.stop': { en: 'Stop following', tr: 'Takibi bırak', es: 'Dejar de seguir' },
  'player.none': { en: 'No moments for {name} in this clip yet.', tr: 'Bu klipte henüz {name} için an yok.', es: 'Aún no hay momentos de {name} en este clip.' },
  'feed.unavailable': { en: 'AI VIEW unavailable. Broadcast remains available.', tr: 'YZ GÖRÜNÜMÜ kullanılamıyor. Yayın görüntüsü açık.', es: 'VISTA IA no disponible. La retransmisión sigue disponible.' },
  'feed.loading': { en: 'Loading AI VIEW…', tr: 'YZ GÖRÜNÜMÜ yükleniyor…', es: 'Cargando VISTA IA…' },
  'feed.caption': {
    en: 'The AI watches the full-pitch feed. Detection boxes are in that video; browser cards are presentation overlays, not vision input.',
    tr: 'Yapay zekâ tüm sahayı gösteren görüntüyü izler. Tespit kutuları o videodadır; tarayıcıdaki kartlar sunum katmanıdır, görüntü işlemenin girdisi değildir.',
    es: 'La IA ve la imagen de todo el campo. Los recuadros de detección están en ese vídeo; las tarjetas del navegador son gráficos de presentación, no entrada de visión.',
  },
  'notice.match': { en: '{language} overlays are not available for this match.', tr: 'Bu maç için {language} grafik yok.', es: 'No hay gráficos en {language} para este partido.' },
  'notice.mode': { en: '{language} overlays are not available for this mode.', tr: 'Bu mod için {language} grafik yok.', es: 'No hay gráficos en {language} para este modo.' },
  'language.en': { en: 'English', tr: 'İngilizce', es: 'inglés' },
  'language.tr': { en: 'Turkish', tr: 'Türkçe', es: 'turco' },
  'language.es': { en: 'Spanish', tr: 'İspanyolca', es: 'español' },

  // head to head
  'compare.kicker': { en: 'HEAD TO HEAD', tr: 'KARŞI KARŞIYA', es: 'CARA A CARA' },
  'compare.title': { en: 'This clip', tr: 'Bu klip', es: 'Este clip' },
  'compare.soFar': { en: 'so far', tr: 'şu ana kadar', es: 'hasta ahora' },
  'stat.SHOTS': { en: 'SHOTS', tr: 'ŞUT', es: 'TIROS' },
  'stat.GOALS': { en: 'GOALS', tr: 'GOL', es: 'GOLES' },
  'stat.PASSES': { en: 'PASSES', tr: 'PAS', es: 'PASES' },
  'stat.PASS ACCURACY %': { en: 'PASS ACCURACY %', tr: 'PAS İSABETİ %', es: 'PRECISIÓN DE PASE %' },
  'stat.YELLOW CARDS': { en: 'YELLOW CARDS', tr: 'SARI KART', es: 'TARJETAS AMARILLAS' },
  'stat.RED CARDS': { en: 'RED CARDS', tr: 'KIRMIZI KART', es: 'TARJETAS ROJAS' },

  // lineups
  'lineups.kicker': { en: 'ON THE PITCH', tr: 'SAHADA', es: 'EN EL CAMPO' },
  'lineups.title': { en: 'Lineups', tr: 'Kadrolar', es: 'Alineaciones' },
  'lineups.card': { en: 'LINEUPS', tr: 'KADROLAR', es: 'ALINEACIONES' },
  'lineups.cardAria': { en: 'Lineups at the clip start', tr: 'Klip başındaki kadrolar', es: 'Alineaciones al inicio del clip' },
  'lineups.skip': { en: 'SKIP', tr: 'GEÇ', es: 'SALTAR' },
  'lineups.players': { en: '{n} PLAYERS', tr: '{n} OYUNCU', es: '{n} JUGADORES' },
  'lineups.on': { en: "ON {m}'", tr: "GİRDİ {m}'", es: "ENTRA {m}'" },
  'lineups.off': { en: "OFF {m}'", tr: "ÇIKTI {m}'", es: "SALE {m}'" },
  'lineups.offFor': { en: "OFF {m}' · {player} ON", tr: "ÇIKTI {m}' · {player} GİRDİ", es: "SALE {m}' · ENTRA {player}" },
  'lineups.sentOff': { en: "SENT OFF {m}'", tr: "ATILDI {m}'", es: "EXPULSADO {m}'" },
  'lineups.offHead': { en: 'OFF', tr: 'OYUNDAN ÇIKANLAR', es: 'FUERA' },
  'lineups.booked': { en: 'Booked', tr: 'Sarı kart gördü', es: 'Amonestado' },
  'lineups.replaced': { en: 'Replaced {name}', tr: '{name} yerine', es: 'Sustituyó a {name}' },
  'lineups.panel': { en: "ON THE PITCH · {m}'", tr: "SAHADA · {m}'", es: "EN EL CAMPO · {m}'" },
  'lineups.panelAria': { en: 'On the pitch', tr: 'Sahada', es: 'En el campo' },
  'lineups.close': { en: 'Close lineups', tr: 'Kadroları kapat', es: 'Cerrar alineaciones' },

  // panels
  'panel.close': { en: 'CLOSE', tr: 'KAPAT', es: 'CERRAR' },
  'panel.closeAria': { en: 'Close', tr: 'Kapat', es: 'Cerrar' },
  'analysis.title': { en: 'CLIP ANALYSIS', tr: 'KLİP ANALİZİ', es: 'ANÁLISIS DEL CLIP' },
  'analysis.aria': { en: 'Clip analysis', tr: 'Klip analizi', es: 'Análisis del clip' },
  'analysis.close': { en: 'Close clip analysis', tr: 'Klip analizini kapat', es: 'Cerrar análisis del clip' },
  'analysis.window': { en: "CLIP {from}'–{to}' · WHAT THE AI SAW", tr: "KLİP {from}'–{to}' · YAPAY ZEKÂNIN GÖRDÜKLERİ", es: "CLIP {from}'–{to}' · LO QUE VIO LA IA" },
  'analysis.fullClip': { en: 'FULL-CLIP REPORT · FINAL SCORE SHOWN', tr: 'TÜM KLİBİN RAPORU · SON SKOR GÖSTERİLİR', es: 'INFORME DEL CLIP COMPLETO · MUESTRA EL RESULTADO FINAL' },
  'analysis.hedged': { en: 'HEDGED', tr: 'TEMKİNLİ', es: 'CON RESERVAS' },
  'analysis.seen': { en: '{pct} SEEN', tr: '{pct} GÖRÜLDÜ', es: '{pct} VISTO' },
  'analysis.short': { en: 'This clip is too short for a tactical read.', tr: 'Bu klip taktik bir okuma için çok kısa.', es: 'Este clip es demasiado corto para una lectura táctica.' },
  'analysis.unseen': { en: 'Too little of the clip was seen for a tactical insight.', tr: 'Taktik bir çıkarım için klibin çok azı görülebildi.', es: 'Se vio muy poco del clip para un análisis táctico.' },
  'analysis.noLanguage': { en: 'No clip analysis in {lang}.', tr: '{lang} dilinde klip analizi yok.', es: 'No hay análisis del clip en {lang}.' },
  'analysis.noInsight': { en: 'No insight in {lang}.', tr: '{lang} dilinde çıkarım yok.', es: 'No hay análisis en {lang}.' },
  'analysis.note': {
    en: "Covers this clip only, from the vision AI's tracking and events. Written by the analyst agent from tactical facts computed by code; every number is from those facts. Click an insight for its evidence.",
    tr: 'Yalnızca bu klibi, görüntü işleme yapay zekâsının takip verisinden ve olaylarından kapsar. Analist ajan, kodun hesapladığı taktik verilerden yazdı; her sayı bu verilerden gelir. Kanıtını görmek için bir çıkarıma tıklayın.',
    es: 'Cubre solo este clip, a partir del seguimiento y los eventos de la IA de visión. Lo escribe el agente analista con datos tácticos calculados por código; cada número sale de esos datos. Haz clic en un análisis para ver su evidencia.',
  },
  'topic.shape': { en: 'SHAPE', tr: 'DİZİLİŞ', es: 'FORMA' },
  'topic.defensive_line': { en: 'LINE HEIGHT', tr: 'SAVUNMA HATTI', es: 'ALTURA DE LÍNEA' },
  'topic.compactness': { en: 'COMPACTNESS', tr: 'KOMPAKTLIK', es: 'COMPACIDAD' },
  'topic.width': { en: 'WIDTH', tr: 'GENİŞLİK', es: 'AMPLITUD' },
  'topic.flanks': { en: 'FLANKS', tr: 'KANATLAR', es: 'BANDAS' },
  'topic.pressing': { en: 'PRESSING', tr: 'PRES', es: 'PRESIÓN' },
  'topic.directness': { en: 'DIRECTNESS', tr: 'DİKEY OYUN', es: 'JUEGO DIRECTO' },
  'topic.progression': { en: 'PROGRESSION', tr: 'İLERLEME', es: 'PROGRESIÓN' },
  'topic.change': { en: 'CHANGE', tr: 'DEĞİŞİM', es: 'CAMBIO' },
  'insight.title': { en: 'INSIGHT EVIDENCE', tr: 'ÇIKARIM KANITI', es: 'EVIDENCIA DEL ANÁLISIS' },
  'insight.facts': { en: 'FACTS (CODE)', tr: 'VERİLER (KOD)', es: 'DATOS (CÓDIGO)' },
  'insight.basedOn': { en: 'Based on {pct} of the clip', tr: 'Klibin {pct} kadarına dayanır', es: 'Basado en el {pct} del clip' },
  'insight.belowHedged': { en: '{seen}, below {pct}: hedged', tr: '{seen}, {pct} altında: temkinli', es: '{seen}, por debajo del {pct}: con reservas' },
  'insight.cited1': { en: '1 cited event', tr: '1 kaynak olay', es: '1 evento citado' },
  'insight.citedN': { en: '{n} cited events', tr: '{n} kaynak olay', es: '{n} eventos citados' },
  'insight.more1': { en: 'and 1 more cited event', tr: 've 1 kaynak olay daha', es: 'y 1 evento citado más' },
  'insight.moreN': { en: 'and {n} more cited events', tr: 've {n} kaynak olay daha', es: 'y {n} eventos citados más' },
  'insight.frameFacts': { en: 'Frame facts: no single event; see the frames counted above.', tr: 'Kare verileri: tek bir olay yok; yukarıda sayılan karelere bakın.', es: 'Datos de fotogramas: sin un evento concreto; ver los fotogramas contados arriba.' },
  'fact.seen': { en: '{pct} seen', tr: '{pct} görüldü', es: '{pct} visto' },
  'fact.frames': { en: '{n} frames', tr: '{n} kare', es: '{n} fotogramas' },
  'fact.events': { en: '{n} events', tr: '{n} olay', es: '{n} eventos' },

  // evidence
  'evidence.title': { en: 'SOURCE EVENTS', tr: 'KAYNAK OLAYLAR', es: 'EVENTOS DE ORIGEN' },
  'evidence.from': { en: 'FROM', tr: 'YAPAN', es: 'DE' },
  'evidence.to': { en: 'TO', tr: 'ALAN', es: 'A' },
  'evidence.team': { en: 'TEAM', tr: 'TAKIM', es: 'EQUIPO' },
  'evidence.start': { en: 'START', tr: 'BAŞLANGIÇ', es: 'INICIO' },
  'evidence.end': { en: 'END', tr: 'BİTİŞ', es: 'FIN' },
  'evidence.cv': { en: 'CV · Detected from video', tr: 'CV · Videodan tespit edildi', es: 'CV · Detectado en el vídeo' },
  'evidence.sim': { en: 'SIM · Simulator', tr: 'SIM · Simülatör', es: 'SIM · Simulador' },
  'evidence.unknown': { en: 'Unknown source', tr: 'Bilinmeyen kaynak', es: 'Fuente desconocida' },
  'evidence.confidence': { en: 'CV confidence: {value}', tr: 'CV güveni: {value}', es: 'Confianza CV: {value}' },
  'evidence.na': { en: 'Not available', tr: 'Yok', es: 'No disponible' },
  'evidence.derived': { en: 'DERIVED', tr: 'HESAPLANAN', es: 'CALCULADO' },

  // cards (drawn on the canvas, in the card's own language)
  'kind.pass_card': { en: 'PASS', tr: 'PAS', es: 'PASE' },
  'kind.shot_card': { en: 'SHOT', tr: 'ŞUT', es: 'TIRO' },
  'kind.goal_banner': { en: 'GOAL', tr: 'GOL', es: 'GOL' },
  'kind.insight_text': { en: 'INSIGHT', tr: 'ANALİZ', es: 'ANÁLISIS' },
  'kind.player_tag': { en: 'PLAYER', tr: 'OYUNCU', es: 'JUGADOR' },
  'kind.speed_badge': { en: 'SPEED', tr: 'HIZ', es: 'VELOCIDAD' },
  'kind.distance_badge': { en: 'DISTANCE', tr: 'MESAFE', es: 'DISTANCIA' },
  'kind.stat_compare': { en: 'STATS', tr: 'İSTATİSTİK', es: 'ESTADÍSTICAS' },
  'kind.momentum_bar': { en: 'MOMENTUM', tr: 'MOMENTUM', es: 'DOMINIO' },
  'kind.red_card': { en: 'RED CARD', tr: 'KIRMIZI KART', es: 'TARJETA ROJA' },
  'kind.yellow_card': { en: 'YELLOW CARD', tr: 'SARI KART', es: 'TARJETA AMARILLA' },
  'cell.distance_m': { en: 'DISTANCE', tr: 'MESAFE', es: 'DISTANCIA' },
  'cell.goal_distance_m': { en: 'RANGE', tr: 'KALEYE UZAKLIK', es: 'DISTANCIA A PORTERÍA' },
  'cell.speed_kmh': { en: 'BALL SPEED', tr: 'TOP HIZI', es: 'VELOCIDAD DEL BALÓN' },
  'cell.difficulty': { en: 'DIFFICULTY', tr: 'ZORLUK', es: 'DIFICULTAD' },
  'cell.xg': { en: 'XG', tr: 'XG', es: 'XG' },
  'cell.pitch': { en: 'PITCH POSITION', tr: 'SAHADAKİ KONUM', es: 'POSICIÓN EN EL CAMPO' },
  'cell.info': { en: 'INFO', tr: 'BİLGİ', es: 'INFO' },
  'card.team': { en: 'Team', tr: 'Takım', es: 'Equipo' },

  // event types and subtypes (evidence panel)
  'event.kickoff': { en: 'kickoff', tr: 'başlama vuruşu', es: 'saque inicial' },
  'event.pass': { en: 'pass', tr: 'pas', es: 'pase' },
  'event.possession_change': { en: 'possession change', tr: 'top el değiştirdi', es: 'cambio de posesión' },
  'event.clearance': { en: 'clearance', tr: 'uzaklaştırma', es: 'despeje' },
  'event.throw_in': { en: 'throw-in', tr: 'taç', es: 'saque de banda' },
  'event.shot': { en: 'shot', tr: 'şut', es: 'tiro' },
  'event.free_kick': { en: 'free kick', tr: 'serbest vuruş', es: 'tiro libre' },
  'event.foul': { en: 'foul', tr: 'faul', es: 'falta' },
  'event.goal_kick': { en: 'goal kick', tr: 'kale vuruşu', es: 'saque de puerta' },
  'event.corner': { en: 'corner', tr: 'korner', es: 'córner' },
  'event.substitution': { en: 'substitution', tr: 'oyuncu değişikliği', es: 'sustitución' },
  'event.offside': { en: 'offside', tr: 'ofsayt', es: 'fuera de juego' },
  'event.yellow_card': { en: 'yellow card', tr: 'sarı kart', es: 'tarjeta amarilla' },
  'event.red_card': { en: 'red card', tr: 'kırmızı kart', es: 'tarjeta roja' },
  'event.goal': { en: 'goal', tr: 'gol', es: 'gol' },
  'event.half_time': { en: 'half time', tr: 'devre arası', es: 'descanso' },
  'event.full_time': { en: 'full time', tr: 'maç sonu', es: 'final' },
  'subtype.short': { en: 'short', tr: 'kısa', es: 'corto' },
  'subtype.long': { en: 'long', tr: 'uzun', es: 'largo' },
  'subtype.cross': { en: 'cross', tr: 'orta', es: 'centro' },
  'subtype.through': { en: 'through', tr: 'ara pası', es: 'al hueco' },
  'subtype.tackle': { en: 'tackle', tr: 'müdahale', es: 'entrada' },
  'subtype.interception': { en: 'interception', tr: 'pas arası', es: 'intercepción' },
  'subtype.on_target': { en: 'on target', tr: 'isabetli', es: 'a puerta' },
  'subtype.off_target': { en: 'off target', tr: 'isabetsiz', es: 'fuera' },
  'subtype.blocked': { en: 'blocked', tr: 'engellendi', es: 'bloqueado' },
  'subtype.open_play': { en: 'open play', tr: 'akan oyun', es: 'jugada' },
  'subtype.penalty': { en: 'penalty', tr: 'penaltı', es: 'penalti' },
  'subtype.own_goal': { en: 'own goal', tr: 'kendi kalesine', es: 'en propia puerta' },
  'subtype.direct': { en: 'direct', tr: 'direkt', es: 'directo' },
  'subtype.straight_red': { en: 'straight red', tr: 'direkt kırmızı', es: 'roja directa' },
  'subtype.second_yellow': { en: 'second yellow', tr: 'ikinci sarı', es: 'segunda amarilla' },

  // how it works
  'pipeline.kicker': { en: 'THE PIPELINE', tr: 'AKIŞ', es: 'EL PROCESO' },
  'pipeline.title': { en: 'How the broadcast gets made', tr: 'Yayın nasıl hazırlanıyor', es: 'Cómo se hace la retransmisión' },
  'pipeline.simulator': { en: 'SIMULATOR', tr: 'SİMÜLATÖR', es: 'SIMULADOR' },
  'pipeline.simulator.text': { en: 'Generates a fictional match: true events and per-frame player positions.', tr: 'Kurgusal bir maç üretir: gerçek olaylar ve her karede oyuncu konumları.', es: 'Genera un partido ficticio: eventos reales y posiciones de los jugadores en cada fotograma.' },
  'pipeline.renderer': { en: 'RENDERER', tr: 'GÖRSELLEŞTİRİCİ', es: 'RENDERIZADOR' },
  'pipeline.renderer.text': { en: 'Turns positions into broadcast-style video at 25 fps.', tr: 'Konumları 25 fps yayın tarzı videoya çevirir.', es: 'Convierte las posiciones en vídeo de estilo televisivo a 25 fps.' },
  'pipeline.vision': { en: 'VISION AI', tr: 'GÖRÜNTÜ İŞLEME', es: 'IA DE VISIÓN' },
  'pipeline.vision.text': { en: 'Watches the video only — detects, tracks, and derives events frame by frame.', tr: 'Yalnızca videoyu izler: kare kare tespit eder, takip eder ve olayları çıkarır.', es: 'Solo ve el vídeo: detecta, sigue y deduce los eventos fotograma a fotograma.' },
  'pipeline.stats': { en: 'STATS', tr: 'İSTATİSTİK', es: 'ESTADÍSTICAS' },
  'pipeline.stats.text': { en: 'Plain code computes the exact numbers: distance, speed, possession.', tr: 'Sayıları düz kod hesaplar: mesafe, hız, topa sahip olma.', es: 'El código calcula las cifras exactas: distancia, velocidad, posesión.' },
  'pipeline.agents': { en: 'AGENTS', tr: 'AJANLAR', es: 'AGENTES' },
  'pipeline.agents.text': { en: 'Explain why a moment matters, verify every number, direct which graphic airs.', tr: 'Bir anın neden önemli olduğunu açıklar, her sayıyı doğrular, hangi grafiğin yayına gireceğine karar verir.', es: 'Explican por qué importa una jugada, verifican cada número y deciden qué gráfico sale al aire.' },
  'pipeline.overlays': { en: 'OVERLAYS', tr: 'GRAFİKLER', es: 'GRÁFICOS' },
  'pipeline.overlays.text': { en: 'Timed JSON: what to show, for how long, in which mode and language.', tr: 'Zamanlı JSON: ne gösterilecek, ne kadar süre, hangi mod ve dilde.', es: 'JSON con tiempos: qué mostrar, cuánto tiempo, en qué modo e idioma.' },
  'pipeline.web': { en: 'WEB PLAYER', tr: 'WEB OYNATICI', es: 'REPRODUCTOR WEB' },
  'pipeline.web.text': { en: 'This page — plays the video, draws the overlays, switches mode and language live.', tr: 'Bu sayfa: videoyu oynatır, grafikleri çizer, modu ve dili canlı değiştirir.', es: 'Esta página: reproduce el vídeo, dibuja los gráficos y cambia de modo e idioma en directo.' },
} satisfies Record<string, Entry>;

export type Key = keyof typeof STRINGS;

/** The UI string for `key` in `lang` (English if the language is not one of ours), with `{name}` slots filled. */
export function ui(lang: string, key: Key, vars: Record<string, string | number> = {}): string {
  const entry: Entry = STRINGS[key];
  const text = entry[lang as Lang] ?? entry.en;
  return text.replace(/\{(\w+)\}/g, (slot, name) => (name in vars ? String(vars[name]) : slot));
}

/** A string from a dynamic key (an event type, a topic), or `fallback` when the table has none. */
export function trMaybe(lang: string, key: string, fallback: string): string {
  return key in STRINGS ? ui(lang, key as Key) : fallback;
}

/**
 * Translate the static page: `data-i18n` sets an element's text, `data-i18n-aria` its aria-label;
 * called on load and on every language switch.
 */
export function applyStaticText(root: ParentNode, lang: string): void {
  root.querySelectorAll<HTMLElement>('[data-i18n]').forEach(el => { el.textContent = ui(lang, el.dataset.i18n as Key); });
  root.querySelectorAll<HTMLElement>('[data-i18n-aria]').forEach(el => { el.setAttribute('aria-label', ui(lang, el.dataset.i18nAria as Key)); });
}
