import { Easing, interpolate, spring } from 'remotion';

export const FPS = 30;

export const C = {
  bg: '#060a13',
  panel: 'rgba(17, 24, 39, 0.82)',
  line: 'rgba(148, 170, 210, 0.18)',
  text: '#eef2fa',
  sub: '#9aa8c0',
  muted: '#5d6b84',
  blue: '#4f8cff',
  cyan: '#38d5e8',
  green: '#3ddc84',
  amber: '#ffc04d',
  red: '#ff5d63',
  violet: '#9b8cff',
};

export const SANS = "-apple-system, 'SF Pro Display', 'PingFang SC', 'Hiragino Sans GB', sans-serif";
export const MONO = "'SF Mono', Menlo, 'PingFang SC', monospace";

export const ease = Easing.bezier(0.22, 1, 0.36, 1);

/** 0→1 progress between frames a and b with a smooth ease-out. */
export const prog = (frame: number, a: number, b: number) =>
  interpolate(frame, [a, b], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease });

export const pop = (frame: number, fps: number, delay = 0, damping = 14) =>
  spring({ frame: frame - delay, fps, config: { damping, stiffness: 160, mass: 0.7 } });

export const fmt = (n: number) => Math.round(n).toLocaleString('en-US');

/** Characters of `text` revealed at `cps` characters per second starting at `start`. */
export const typed = (text: string, frame: number, start: number, cps = 28) =>
  text.slice(0, Math.max(0, Math.floor(((frame - start) / FPS) * cps)));
