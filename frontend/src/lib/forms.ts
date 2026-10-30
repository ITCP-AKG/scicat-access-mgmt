// Non-component helpers shared by forms (kept apart so components hot-reload cleanly).
import type { DirectoryUser, GroupCategory } from '../api/types';

export const CATEGORIES: GroupCategory[] = [
  'research-group',
  'project',
  'administrative',
  'instrument',
  'other',
];

export interface TemporalWindow {
  effectiveFrom: string | null;
  expiresAt: string | null;
}

export const EMPTY_WINDOW: TemporalWindow = { effectiveFrom: null, expiresAt: null };

/** Why a window is invalid (mirrors the backend's check), or null. */
export function windowError(value: TemporalWindow): string | null {
  const from = value.effectiveFrom ? Date.parse(value.effectiveFrom) : null;
  const to = value.expiresAt ? Date.parse(value.expiresAt) : null;
  if (to !== null && to <= Date.now()) return 'Expiry must be in the future';
  if (from !== null && to !== null && from >= to) return 'Start must be before expiry';
  return null;
}

/** The name a user is shown by everywhere in the app. */
export function userName(u: DirectoryUser): string {
  return u.displayName || u.username || u.userId;
}

/** Admin-facing label: name, account alias and e-mail are all shown explicitly here
 *  (catorga itself only ever shows the name). */
export function userLabel(u: DirectoryUser): string {
  const name = userName(u);
  const parts = [name, u.username && u.username !== name ? u.username : '', u.email].filter(Boolean);
  return `${parts.join(' · ')}${u.active ? '' : ' — departed'}`;
}
