export interface Team {
  name: string; short: string; kit: { shirt: string; shorts: string; goalkeeper?: string };
  formation?: string; style?: 'possession' | 'counter' | 'pressing' | 'direct' | 'balanced';
  players: { id: number; number: number; name: string; pos: string; starter: boolean }[];
}
export interface MatchInfo {
  match_id: string; fps: number; pitch: number[]; origin: 'bottom-left';
  kickoff_direction?: { home: 'left_to_right' | 'right_to_left' };
  home: Team; away: Team;
  periods?: { period: number; start: number; end: number }[];
}
export interface TrackedPlayer { id: number; team: 'home' | 'away' | 'referee'; pos: number[]; confidence?: number }
export interface Frame { match_id: string; frame: number; t: number; period?: 1 | 2; ball: number[]; players: TrackedPlayer[] }
export interface Match { info: MatchInfo; frames: Frame[] }

export type EventType =
  | 'kickoff' | 'pass' | 'possession_change' | 'clearance' | 'throw_in' | 'shot' | 'free_kick'
  | 'foul' | 'goal_kick' | 'corner' | 'substitution' | 'offside' | 'yellow_card' | 'red_card'
  | 'goal' | 'half_time' | 'full_time';

export interface MatchEvent {
  id: string; match_id: string; t: number; period?: 1 | 2; type: EventType; team?: 'home' | 'away' | 'none';
  from?: number | null; to?: number | null; start?: number[]; end?: number[]; subtype?: string;
  distance_m?: number; speed_kmh?: number; duration_s?: number; success?: boolean;
  score?: { home?: number; away?: number };
  source: 'cv' | 'sim'; confidence?: number;
}

export type OverlayGraphic =
  | 'player_tag' | 'pass_card' | 'shot_card' | 'speed_badge' | 'distance_badge'
  | 'stat_compare' | 'momentum_bar' | 'goal_banner' | 'card_banner' | 'insight_text';

export type OverlayPosition = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right' | 'bottom-center' | 'follow-player';

export type Mode = 'analyst' | 'casual' | 'player_focus';

export interface Overlay {
  id: string; start: number; duration: number; graphic: OverlayGraphic; event_ids: string[];
  player?: number | null; priority?: number; position?: OverlayPosition; title?: string; text: string;
  values?: Record<string, number>; mode: Mode; lang: string;
}

/** Sidecar written by renderer export: maps the exported clip's time back to match time (`matchT = start + video.currentTime`). */
export interface ExportManifest {
  match_id: string; fps: number; width: number; height: number; start: number; end: number;
  rich: boolean; render: { camera: 'cv_full_pitch' | 'broadcast' } & Record<string, unknown>;
  frames: { output_frame: number; t: number; input_frame: number }[];
}
