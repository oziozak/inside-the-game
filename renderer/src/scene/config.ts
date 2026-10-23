export type CameraPreset = 'cv_full_pitch' | 'broadcast';
export interface Visibility { playerScale: number; ballScale: number }
export interface RenderConfig extends Visibility { camera: CameraPreset; cvVisibility: boolean; jerseyNumbers: boolean; animatePlayers: boolean }
export const DEFAULT_CONFIG: Readonly<RenderConfig> = Object.freeze({ camera: 'cv_full_pitch', playerScale: 1, ballScale: 1, cvVisibility: false, jerseyNumbers: false, animatePlayers: true });
export const BALL_RADIUS_M = 0.11;
/** Renderer-only presentation settings; never change tracking data. */
export function renderConfig(input: Partial<RenderConfig> = {}): RenderConfig {
  const config = { ...DEFAULT_CONFIG, ...input };
  if (config.camera !== 'cv_full_pitch' && config.camera !== 'broadcast') throw new Error('Camera must be cv_full_pitch or broadcast');
  if (typeof config.cvVisibility !== 'boolean') throw new Error('cvVisibility must be boolean');
  for (const key of ['jerseyNumbers', 'animatePlayers'] as const) if (typeof config[key] !== 'boolean') throw new Error(`${key} must be boolean`);
  for (const key of ['playerScale', 'ballScale'] as const) {
    if (!Number.isFinite(config[key]) || config[key] < 0.25 || config[key] > 5) throw new Error(`${key} must be between 0.25 and 5`);
  }
  return config;
}
