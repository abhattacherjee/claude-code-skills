# Scene Architecture Reference

## Table of Contents
- [Standard Scene Structure](#standard-scene-structure)
- [Phone Mockup Components](#phone-mockup-components)
- [Animation Patterns](#animation-patterns)
- [Aspect Ratio Layouts](#aspect-ratio-layouts)
- [Brand Integration](#brand-integration)

## Standard Scene Structure

Every product video follows this 7-scene arc:

| # | Scene | Purpose | Duration |
|---|-------|---------|----------|
| 1 | **Hook** | Problem statement — grab attention | 4-5s |
| 2 | **Intro** | Product name + value proposition | 5-6s |
| 3 | **App Showcase** | Animated phone cycling through app screens | 10-12s |
| 4 | **Vibes/Features** | Visual feature cards with icons | 6-7s |
| 5 | **How It Works** | 3-step numbered process | 7-8s |
| 6 | **Results** | Scrolling phone showing output/results | 10-12s |
| 7 | **CTA** | Closing headline + call to action | 5-6s |

### Scene Sequencing with Crossfades

Overlap `<Sequence>` start frames by 10-15 frames for smooth crossfades:
```tsx
<Sequence durationInFrames={150}><HookScene /></Sequence>
<Sequence from={140} durationInFrames={160}><IntroScene /></Sequence>
```

Each scene handles its own fade-in/fade-out via `interpolate()` on opacity.

## Phone Mockup Components

### Three Phone Variants

1. **PhoneMockup** — static screenshot in a phone frame
2. **AnimatedPhone** — crossfades between multiple screenshots sequentially
3. **ScrollingPhone** — tall full-page screenshot with animated vertical scroll

### iPhone Dynamic Island Style

All phone frames use a pill-shaped Dynamic Island (not the old wide notch):
```tsx
{/* Dynamic Island */}
<div
  className="absolute left-1/2 -translate-x-1/2 z-20 bg-black rounded-full"
  style={{ width: 100 * s, height: 28 * s, top: pad + 10 * s }}
/>
```

### Phone Frame Dimensions (at scale=1)

- Outer: 440×950px, border-radius: 60px
- Padding: 14px
- Screen: 412×922px, border-radius: 48px
- Shadow: `0 30px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.08)`

### AnimatedPhone Crossfade Logic

Each screen gets `holdFrames` (default 45 = 1.5s) then `transitionFrames` (15 = 0.5s) crossfade.
The last screen can optionally scroll through a full-page screenshot using `scrollExtraFrames`.

### ScrollingPhone Easing

Use quadratic ease-in-out for natural scroll feel:
```tsx
const eased = progress < 0.5
  ? 2 * progress * progress
  : 1 - Math.pow(-2 * progress + 2, 2) / 2;
```

## Animation Patterns

### Entry Animations
- **spring()** for element entries — `damping: 14, mass: 0.8` for standard, lower damping for bouncier
- **Staggered delays** — increment by 10-25 frames per element for cascade reveals
- **translateY + opacity** for text entries: `translateY(${interpolate(spring, [0, 1], [30, 0])}px)`

### Ambient Effects
- **Floating phones**: `Math.sin(frame * 0.025) * 4` — 4px amplitude, slow oscillation
- **Pulsing glow**: `Math.sin(frame * 0.08) * 0.3 + 0.7` on box-shadow
- **Radial gradient orbs** — `radial-gradient(circle, rgba(color,0.08) 0%, transparent 70%)`

### Remotion-Specific Rules
- **Never use CSS transitions** — they cause flickering in rendered output. All animations must derive from `useCurrentFrame()`
- **Use `<Img>` from remotion** — not `<img>` — for proper frame-level loading
- **Use `staticFile()`** for public/ assets

## Aspect Ratio Layouts

### 9:16 (Instagram Reels / TikTok) — 1080×1920
- Text: center-aligned, stacked vertically
- Phone mockups: max 2 side-by-side (2×2 grid), or 1 large centered
- Feature cards: 2×2 grid (not 4 in a row)
- How It Works: heading on top, steps stacked below
- Results: text on top, scrolling phone below

### 16:9 (YouTube / Landscape) — 1920×1080
- Text + phones: side-by-side layout (text left, phones right)
- Feature cards: 4 in a row
- How It Works: heading left, steps right
- Results: text left, phone(s) right

### 1:1 (Instagram Post) — 1080×1080
- Compact layouts, larger fonts relative to canvas
- Single phone mockup centered
- 2×2 grid for cards

## Brand Integration

### Extracting from Brand Guidelines PDF

Use `pdftotext` to extract colors, fonts, and tone. Key elements to capture:

1. **Color palette** — map to: background, accent/highlight, organic/natural, text
2. **Typography** — map to: headings (display font), accents/labels (sans-serif), body (serif/readable)
3. **Tone keywords** — inform copy style (warm, sensory, mindful, etc.)

### Typical Color Mapping

| Role | CSS Property | Example |
|------|-------------|---------|
| Background | `bg-[#hex]` on AbsoluteFill | Dark charcoal or deep tone |
| Primary accent | Highlighted text, CTA borders, dots | Brand's warm/vibrant color |
| Secondary | Labels, step indicators | Brand's organic/natural color |
| Text | Headings | White or off-white |
| Muted text | Descriptions, body copy | 60-70% opacity of text color |

### Google Fonts in Remotion

Load via CSS `@import` in `index.css`:
```css
@import "tailwindcss";
@import url('https://fonts.googleapis.com/css2?family=Font1&family=Font2&display=swap');
```

Apply via inline styles (not Tailwind classes) for font-family:
```tsx
style={{ fontFamily: "Playfair Display, serif", fontWeight: 400 }}
```

## Screenshot Capture Best Practices

### Hiding UI Overlays
Fixed-position elements (theme toggles, cookie banners) interfere with Playwright clicks.
Hide them before interacting:
```js
await page.evaluate(() => {
  document.querySelectorAll('.fixed').forEach(el => el.style.display = 'none');
});
```

### Full-Page Screenshots for Scrolling
Capture with `fullPage: true` and note the CSS height (`scrollHeight`) for ScrollingPhone's `imageHeight` prop.
Use `scrollFraction` (0-1) to control how far through the page the animation scrolls.

### Mobile Viewport Settings
```js
{ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }
```
This produces 780px-wide images at 2x DPR — matches iPhone 14 Pro dimensions.
