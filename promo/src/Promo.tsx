import React from 'react';
import { AbsoluteFill } from 'remotion';
import { TransitionSeries, linearTiming, springTiming } from '@remotion/transitions';
import { fade } from '@remotion/transitions/fade';
import { slide } from '@remotion/transitions/slide';
import { Backdrop } from './parts';
import { SANS } from './theme';
import { Base, Card, Decision, Hook, Outro, Result, Topics, Understand } from './scenes';

const T = 14;
export const SCENES: [React.FC, number][] = [
  [Hook, 80], [Understand, 112], [Base, 112], [Topics, 80], [Card, 84], [Decision, 84], [Result, 76], [Outro, 96],
];
export const DURATION = SCENES.reduce((s, [, d]) => s + d, 0) - T * (SCENES.length - 1);

const transitions = [
  fade(), slide({ direction: 'from-right' }), slide({ direction: 'from-right' }), slide({ direction: 'from-bottom' }),
  slide({ direction: 'from-right' }), slide({ direction: 'from-bottom' }), fade(),
];

export const Promo: React.FC = () => (
  <AbsoluteFill style={{ fontFamily: SANS }}>
    <Backdrop />
    <TransitionSeries>
      {SCENES.flatMap(([Scene, d], i) => {
        const items = [
          <TransitionSeries.Sequence key={`s${i}`} durationInFrames={d}>
            <Scene />
          </TransitionSeries.Sequence>,
        ];
        if (i < SCENES.length - 1) {
          items.push(
            <TransitionSeries.Transition key={`t${i}`} presentation={transitions[i] as never}
              timing={i === 0 || i === SCENES.length - 2 ? linearTiming({ durationInFrames: T }) : springTiming({ config: { damping: 200 }, durationInFrames: T })} />,
          );
        }
        return items;
      })}
    </TransitionSeries>
  </AbsoluteFill>
);
