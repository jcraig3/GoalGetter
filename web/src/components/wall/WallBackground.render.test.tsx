// @vitest-environment jsdom
/**
 * What sits behind a wall screen.
 *
 * **It was stored, validated and inherited for a phase before anything drew
 * it.** The whole shape — kind, colours, asset, dim, blur — resolved correctly
 * through four layers and reached a television that painted near-black over
 * the top of it. These are the tests that would have caught that.
 */
import { render } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import WallBackground from './WallBackground';
import type { Background } from '../../appearance';

const background = (over: Partial<Background> = {}): Background => ({
  kind: 'none',
  color: null,
  color_to: null,
  asset: null,
  dim: null,
  blur: null,
  ...over,
});

// `:scope`, because Testing Library's own container is a div — so a bare
// `div > div` matches the component's root rather than the layer inside it.
const layerOf = (container: HTMLElement) =>
  container.querySelector(':scope > div > div') as HTMLElement | null;

describe('WallBackground', () => {
  test('draws nothing when there is nothing to draw', () => {
    const { container } = render(<WallBackground background={background()} />);

    expect(container.firstChild).toBeNull();
  });

  test('draws nothing rather than throwing when there is no background at all', () => {
    const { container } = render(<WallBackground background={null} />);

    expect(container.firstChild).toBeNull();
  });

  test('"inherit" never blanks a wall', () => {
    // `resolve` collapses it before a renderer sees one, but an older row and
    // newer code is exactly the case where a television goes dark.
    const { container } = render(
      <WallBackground background={background({ kind: 'inherit' })} />,
    );

    expect(container.firstChild).toBeNull();
  });

  test('a solid colour', () => {
    const { container } = render(
      <WallBackground background={background({ kind: 'solid', color: '#ff0000' })} />,
    );

    expect(layerOf(container)?.style.backgroundColor).toBe('rgb(255, 0, 0)');
  });

  test('a gradient uses both stops', () => {
    const { container } = render(
      <WallBackground
        background={background({
          kind: 'gradient',
          color: '#ff0000',
          color_to: '#0000ff',
        })}
      />,
    );

    const image = layerOf(container)?.style.backgroundImage ?? '';
    expect(image).toContain('linear-gradient');
    expect(image).toContain('rgb(255, 0, 0)');
    expect(image).toContain('rgb(0, 0, 255)');
  });

  test('a gradient with one stop is a gradient, not a crash', () => {
    // Somebody picks "gradient" and sets the first colour. Between those two
    // actions the second is null.
    const { container } = render(
      <WallBackground
        background={background({ kind: 'gradient', color: '#ff0000' })}
      />,
    );

    expect(layerOf(container)?.style.backgroundImage).toContain('linear-gradient');
  });

  test('a photograph goes through the caller’s url builder', () => {
    // A television authenticates with the token in its own address.
    const { container } = render(
      <WallBackground
        background={background({ kind: 'image', asset: 'abc123' })}
        imageUrl={(d) => `/api/display/t/assets/${d}`}
      />,
    );

    expect(layerOf(container)?.style.backgroundImage).toContain(
      '/api/display/t/assets/abc123',
    );
  });

  test('a photograph covers, because a television is 16:9 and it is not', () => {
    const { container } = render(
      <WallBackground background={background({ kind: 'image', asset: 'abc' })} />,
    );

    expect(layerOf(container)?.style.backgroundSize).toBe('cover');
  });

  test('"image" with nothing uploaded yet draws no broken picture', () => {
    const { container } = render(
      <WallBackground background={background({ kind: 'image', asset: null })} />,
    );

    expect(layerOf(container)?.style.backgroundImage).toBe('');
  });

  test('darkening is a layer over the blur, not part of it', () => {
    // Dimming under the blur would blur the dimming too and lighten the edges.
    const { container } = render(
      <WallBackground
        background={background({ kind: 'image', asset: 'abc', dim: 0.5, blur: 8 })}
      />,
    );

    // The picture, the dim over it, and the header's shade over both.
    const layers = container.querySelectorAll(':scope > div > div');
    expect(layers).toHaveLength(3);
    expect((layers[1] as HTMLElement).style.opacity).toBe('0.5');
    expect((layers[2] as HTMLElement).dataset.testid).toBe('header-shade');
  });

  test('a blurred background is scaled past its own edges', () => {
    // A blur samples beyond its bounds and leaves a pale border otherwise,
    // which on a wall reads as a badly cropped photograph.
    const { container } = render(
      <WallBackground background={background({ kind: 'image', asset: 'a', blur: 10 })} />,
    );

    expect(layerOf(container)?.style.filter).toBe('blur(10px)');
    expect(layerOf(container)?.style.transform).toContain('scale');
  });

  test('an unblurred background is not scaled', () => {
    const { container } = render(
      <WallBackground background={background({ kind: 'image', asset: 'a' })} />,
    );

    expect(layerOf(container)?.style.transform).toBe('');
  });

  test('a youtube background plays muted and on a loop', () => {
    // A wall that starts making noise on its own is how a feature gets
    // switched off entirely.
    const { container } = render(
      <WallBackground background={background({ kind: 'youtube', asset: 'dQw4' })} />,
    );

    const src = container.querySelector('iframe')?.getAttribute('src') ?? '';
    expect(src).toContain('mute=1');
    expect(src).not.toContain('playlist=');
  });

  test('sits behind everything, rather than over it', () => {
    // **The bug this pins.** Inside one stacking context a positioned element
    // paints above its in-flow siblings whatever the DOM order — so an
    // `absolute` layer written first still covered the title, the logo and the
    // board. Asserted as a class because jsdom does not paint: the real proof
    // is a television, and this is what stops the class being removed by
    // somebody tidying.
    const { container } = render(
      <WallBackground background={background({ kind: 'solid', color: '#000' })} />,
    );

    expect((container.firstChild as HTMLElement).className).toContain('-z-10');
  });

  test('it never swallows a click meant for the screen', () => {
    const { container } = render(
      <WallBackground background={background({ kind: 'solid', color: '#000' })} />,
    );

    expect((container.firstChild as HTMLElement).className).toContain(
      'pointer-events-none',
    );
  });

  test('an uploaded video plays muted and looping, through the wall URL', () => {
    // Muted is what lets a browser autoplay at all; the URL is the display
    // token's, because a television has no session.
    const { container } = render(
      <WallBackground
        background={background({ kind: 'video', asset: 'abc123' })}
        imageUrl={(digest) => `/api/display/TOKEN/assets/${digest}`}
      />,
    );
    const video = container.querySelector('video') as HTMLVideoElement | null;

    expect(video?.getAttribute('src')).toBe('/api/display/TOKEN/assets/abc123');
    expect(video?.muted).toBe(true);
    expect(video?.loop).toBe(true);
    expect(video?.hasAttribute('playsinline')).toBe(true);
  });

  test('a video is darkened like a photograph', () => {
    // Dim belongs to the background, whatever kind it is — footage behind
    // white text is as unreadable at ten feet as a photograph.
    const { container } = render(
      <WallBackground background={background({ kind: 'video', asset: 'abc', dim: 0.5 })} />,
    );

    const shade = container.querySelector('.bg-black') as HTMLElement | null;
    expect(shade?.style.opacity).toBe('0.5');
  });

  test('a video with no file yet draws no player', () => {
    const { container } = render(
      <WallBackground background={background({ kind: 'video' })} />,
    );

    expect(container.querySelector('video')).toBeNull();
  });
});

describe('the header over a picture', () => {
  test('is shaded behind a photograph, whatever the dim', () => {
    // Grey words over a bright photograph were not there from across a room.
    const { getByTestId } = render(
      <WallBackground background={background({ kind: 'image', asset: 'abc', dim: 0 })} />,
    );

    expect(getByTestId('header-shade')).toBeDefined();
  });

  test('is left alone on a colour, where the colour is the choice', () => {
    const { queryByTestId } = render(
      <WallBackground background={background({ kind: 'solid', color: '#ffcc00' })} />,
    );

    expect(queryByTestId('header-shade')).toBeNull();
  });
});
