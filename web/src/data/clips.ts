/** The clips a multi-clip build holds (clips.json, written by scripts/prepare.mjs), and which one to show. */

export interface Clip { id: string; title: string }

const ID = /^[a-z0-9][a-z0-9_-]{0,39}$/;

/** The clip list from clips.json's parsed body, or undefined when it is not a valid, non-empty list. */
export function parseClips(body: unknown): Clip[] | undefined {
  const clips = (body as { clips?: unknown } | null)?.clips;
  if (!Array.isArray(clips) || !clips.length) return undefined;
  const out: Clip[] = [];
  for (const c of clips) {
    if (!c || typeof c.id !== 'string' || !ID.test(c.id) || out.some(o => o.id === c.id)) return undefined;
    out.push({ id: c.id, title: typeof c.title === 'string' && c.title.trim() ? c.title.trim() : c.id });
  }
  return out;
}

/** The clip named by `?clip=` in `search`, else the first. */
export function pickClip(clips: Clip[], search: string): Clip {
  const wanted = new URLSearchParams(search).get('clip');
  return clips.find(c => c.id === wanted) ?? clips[0];
}

/** Where the page loads its files from: the build root for one clip, its subfolder for several. */
export function clipBase(root: string, clip?: Clip): string {
  return clip ? `${root}/${clip.id}` : root;
}

/** The page's URL with `?clip=` set to `id`, keeping any other query and the hash. */
export function clipUrl(href: string, id: string): string {
  const url = new URL(href);
  url.searchParams.set('clip', id);
  return url.toString();
}

/** clips.json from the build, or undefined for a one-clip build (no file, or a host's HTML fallback). */
export async function loadClips(root: string): Promise<Clip[] | undefined> {
  try {
    const response = await fetch(`${root}/clips.json`, { headers: { Accept: 'application/json' } });
    if (!response.ok || !(response.headers.get('content-type') ?? '').includes('json')) return undefined;
    return parseClips(await response.json());
  } catch {
    return undefined;
  }
}
