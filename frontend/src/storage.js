const STORAGE_PREFIX = 'rehub:';

export function projectStorageKey(scope, projectId) {
  if (!projectId) return '';
  return `${STORAGE_PREFIX}${scope}:${projectId}`;
}

export function readStorage(key, fallback = null) {
  if (!key || typeof window === 'undefined') return fallback;

  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function writeStorage(key, value) {
  if (!key || typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Browsers can reject writes in private mode or when quota is full.
  }
}
