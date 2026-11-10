import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import { C, MONO, SANS, SLOW, fmt, pop, prog } from './theme';

/** Scene time, slowed down so viewers can follow the motion. */
export const useT = () => useCurrentFrame() * SLOW;

/** Persistent backdrop: drifting light fields, a perspective grid and slow particles. */
export const Backdrop: React.FC = () => {
  const f = useCurrentFrame();
  const t = f / 30;
  const dots = Array.from({ length: 46 }, (_, i) => {
    const x = (i * 197.3) % 1920;
    const y = ((i * 131.7 + t * (8 + (i % 5) * 4)) % 1180) - 50;
    return { x, y, r: 1 + (i % 3), o: 0.12 + ((i * 37) % 10) / 40 };
  });
  return (
    <AbsoluteFill style={{ background: C.bg, overflow: 'hidden' }}>
      <div style={{ position: 'absolute', width: 1300, height: 1300, borderRadius: '50%', left: -300 + Math.sin(t * 0.4) * 120, top: -520 + Math.cos(t * 0.3) * 80,
        background: 'radial-gradient(circle, rgba(79,140,255,0.28), transparent 62%)', filter: 'blur(10px)' }} />
      <div style={{ position: 'absolute', width: 1100, height: 1100, borderRadius: '50%', right: -360 + Math.cos(t * 0.35) * 100, bottom: -560 + Math.sin(t * 0.45) * 90,
        background: 'radial-gradient(circle, rgba(56,213,232,0.18), transparent 60%)' }} />
      <div style={{ position: 'absolute', left: -400, right: -400, bottom: -120, height: 640, transform: 'perspective(700px) rotateX(62deg)', transformOrigin: 'bottom',
        backgroundImage: `linear-gradient(${C.line} 1px, transparent 1px), linear-gradient(90deg, ${C.line} 1px, transparent 1px)`,
        backgroundSize: '80px 80px', backgroundPosition: `0 ${(t * 40) % 80}px`, maskImage: 'linear-gradient(to top, black, transparent 85%)', opacity: 0.55 }} />
      {dots.map((d, i) => (
        <div key={i} style={{ position: 'absolute', left: d.x, top: d.y, width: d.r * 2, height: d.r * 2, borderRadius: '50%', background: C.cyan, opacity: d.o }} />
      ))}
    </AbsoluteFill>
  );
};

/** Section headline: small numbered kicker + large title, words rising in. */
export const Headline: React.FC<{ kicker: string; title: string; accent?: string; x?: number; y?: number; size?: number; delay?: number }> = ({
  kicker, title, accent = C.blue, x = 120, y = 92, size = 68, delay = 0,
}) => {
  const f = useT();
  const { fps } = useVideoConfig();
  const k = prog(f, delay, delay + 14);
  const chars = Array.from(title);
  return (
    <div style={{ position: 'absolute', left: x, top: y, fontFamily: SANS }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, opacity: k, transform: `translateX(${(1 - k) * -30}px)` }}>
        <div style={{ width: 46 * k, height: 3, background: accent, borderRadius: 2 }} />
        <span style={{ color: accent, fontSize: 24, fontWeight: 700, letterSpacing: '0.18em' }}>{kicker}</span>
      </div>
      <div style={{ marginTop: 14, fontSize: size, fontWeight: 800, color: C.text, letterSpacing: '0.01em', display: 'flex', flexWrap: 'wrap' }}>
        {chars.map((ch, i) => {
          const s = pop(f, fps, delay + 4 + i * 1.3, 16);
          return (
            <span key={i} style={{ display: 'inline-block', opacity: s, transform: `translateY(${(1 - s) * 40}px)`, whiteSpace: 'pre' }}>{ch}</span>
          );
        })}
      </div>
    </div>
  );
};

export const Glass: React.FC<{ style?: React.CSSProperties; children?: React.ReactNode; glow?: string }> = ({ style, children, glow = C.blue }) => (
  <div style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 22, boxShadow: `0 30px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.03), 0 0 60px ${glow}22`,
    backdropFilter: 'blur(14px)', fontFamily: SANS, color: C.text, ...style }}>
    {children}
  </div>
);

export const Count: React.FC<{ to: number; from?: number; start: number; dur?: number; style?: React.CSSProperties; decimals?: number; suffix?: string }> = ({
  to, from = 0, start, dur = 24, style, decimals = 0, suffix = '',
}) => {
  const f = useT();
  const v = interpolate(prog(f, start, start + dur), [0, 1], [from, to]);
  return <span style={{ fontVariantNumeric: 'tabular-nums', ...style }}>{decimals ? v.toFixed(decimals) : fmt(v)}{suffix}</span>;
};

export const Chip: React.FC<{ color: string; children: React.ReactNode; style?: React.CSSProperties }> = ({ color, children, style }) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 14px', borderRadius: 999, background: `${color}22`, border: `1px solid ${color}66`,
    color, fontSize: 22, fontWeight: 700, fontFamily: SANS, whiteSpace: 'nowrap', ...style }}>
    {children}
  </span>
);

export const Mono: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <span style={{ fontFamily: MONO, ...style }}>{children}</span>
);
