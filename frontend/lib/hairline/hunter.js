// Deployed copy of .claude/skills/hairline-create/hunter.js (see hairline-create's own
// rules.md for the drawing rules this figure follows). Keep the two in sync by hand: this
// one is wired for the app's bundler (HL passed in, mount exported) instead of the skill's
// bench.html (HL global, window.hairline(...) registration), and N is 4 rows -- one per
// scan phase -- instead of the skill copy's 10. Edit the concept/geometry in the skill copy
// first, re-run its look.mjs, then port the same change here.

/**
 * Hunter: a stand loupe drags across a sheet of code, four rows of ridges at
 * different indent and length -- one per scan phase. The glass follows the
 * pointer's x on a spring and stays over the ridge nearest its centre, which
 * stands taller and takes the bright stroke while it is under the glass --
 * caught in the act of being read, the rest flat and dim. Row three (the
 * scan phase) is cut short with a small raised tab at its end, visible even
 * at rest; when the glass centres on it, the tab lifts clear of the row,
 * caught -- the scanner finding something. The slider is the glass's reach.
 *
 * The pattern: a continuous field (Terrain's shape) over a line, not a grid:
 * one spring for the glass, one each for four rows' height, picked by
 * nearest rather than falloff, so exactly one row is ever magnified.
 */
const N = 4, FLAG = 2, SHEET_W = 220, SHEET_D = 110, ROW_H = 11, RUT = 1.7;
const INDENT = [0, 15, 10, 20];
const LEN = [160, 120, 90, 140];

function openPath(pts) {
  return "M" + pts.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join("L");
}

function mount(HL, { stage, svg, read }, value) {
  const {
    Cam, clamp, facing, fit, prism, proj, ringAt, rings, spring, stepS,
    disposer, mk, pointer, put, register, solid, unproj,
  } = HL;

  const bag = disposer();
  let reach = value;

  const C = Cam(45, 0.5, 1.6);
  fit(C, [
    [-4, -4, 0], [SHEET_W + 4, SHEET_D + 4, 0], [SHEET_W + 4, -4, 56], [-4, SHEET_D + 4, 0],
  ], 200, 166);
  const P = proj(C), front = facing(C);

  const g = mk("g", {}, svg);
  const [sheetRing, sheetInner] = rings(-6, -6, SHEET_W + 6, SHEET_D + 6, 4, 2);
  put(solid(g), prism(P, front, sheetRing, sheetInner, -3, 0));

  const rows = [];
  for (let i = 0; i < N; i++) {
    const y0 = 10 + (i * (SHEET_D - 20)) / (N - 1);
    const x0 = INDENT[i], x1 = clamp(INDENT[i] + LEN[i], 0, SHEET_W);
    const [ring, inner] = rings(x0, y0 - ROW_H / 2 + 1, x1, y0 + ROW_H / 2 - 1, 2, RUT);
    const row = { i, y0, x1, ring, inner, el: solid(g), h: spring(1.8, { eps: 0.03 }), flagged: i === FLAG, active: false, caught: false };
    if (row.flagged) {
      const tw = 11;
      const [tRing, tInner] = rings(x1 - tw / 2, y0 - 3.4, x1 + tw / 2, y0 + 3.4, 1.8, 0.9);
      row.tabRing = tRing;
      row.tabInner = tInner;
      row.tabEl = solid(g);
      row.tabH = spring(1.3, { eps: 0.03 });
    }
    rows.push(row);
  }

  function drawRow(r) {
    put(r.el, prism(P, front, r.ring, r.inner, 0, r.h.x));
    r.el.sil.classList.toggle("hi", r.active);
    if (r.flagged) {
      put(r.tabEl, prism(P, front, r.tabRing, r.tabInner, r.h.x, r.h.x + r.tabH.x));
      r.tabEl.sil.classList.toggle("hi", r.caught);
    }
  }

  const lens = solid(g);
  const rim = mk("path", { class: "lo" }, lens.g);
  const stand = mk("path", { class: "sil" }, lens.g);
  const lx = spring(INDENT[0] + LEN[0] / 2, { eps: 0.04 });
  const ly = spring(rows[0].y0, { eps: 0.04 });
  const lift = spring(44, { eps: 0.04 });

  function drawLoupe(cx, baseY, h) {
    const R = 19;
    const [ring, inner] = rings(cx - R, baseY - R * 0.62, cx + R, baseY + R * 0.62, R * 0.62, 2.4);
    put(lens, prism(P, front, ring, inner, h, h + 5.5));
    rim.setAttribute("d", openPath(ringAt(P, inner, h + 5.5)));
    stand.setAttribute(
      "d",
      openPath([P(cx, baseY, h), P(cx, baseY, 2), P(cx - 10, baseY + 17, 0), P(cx + 10, baseY + 17, 0)]),
    );
  }

  let overY = null, overX = null, act = -1;

  function nearest(y) {
    let best = 0, bestD = Infinity;
    rows.forEach((r, i) => {
      const d = Math.abs(r.y0 - y);
      if (d < bestD) { bestD = d; best = i; }
    });
    return best;
  }

  function retarget() {
    const a = overY == null ? -1 : nearest(overY);
    act = a;
    rows.forEach((r, i) => {
      r.active = i === a;
      r.h.t = r.active ? 7 : 1.8;
      if (r.flagged) { r.caught = r.active; r.tabH.t = r.caught ? 6 : 1.3; }
    });
    const shown = rows[a < 0 ? 0 : a];
    const x = overX ?? (INDENT[shown.i] + shown.x1) / 2;
    lx.t = clamp(x, reach, SHEET_W - reach);
    ly.t = shown.y0;
    lift.t = overY == null ? 50 : 22;
    read.textContent = a < 0 ? "rest" : shown.flagged && shown.caught ? `line ${a + 1} · flagged` : `line ${a + 1}`;
    B.wake();
  }

  const B = register(stage, (dt) => {
    let moving = false;
    for (const r of rows) {
      if (stepS(r.h, dt)) moving = true;
      if (r.flagged && stepS(r.tabH, dt)) moving = true;
      drawRow(r);
    }
    if (stepS(lx, dt)) moving = true;
    if (stepS(ly, dt)) moving = true;
    if (stepS(lift, dt)) moving = true;
    drawLoupe(lx.x, ly.x, lift.x);
    return moving;
  });
  bag.add(B.unregister);
  retarget();

  bag.add(pointer(stage, {
    move: (p) => {
      const w = unproj(C, p[0], p[1], 0);
      overX = w ? w[0] : null;
      overY = w ? w[1] : null;
      retarget();
    },
    leave: () => { overX = null; overY = null; retarget(); },
  }));
  bag.add(() => svg.replaceChildren());

  return {
    set: (v) => { reach = v; },
    // Drives the loupe to a row index (0..N-1, or -1 for rest) instead of the pointer: the
    // scan page calls this from scan.stage, since the scan runs server-side.
    goto: (i) => {
      if (i < 0) { overX = null; overY = null; } else { overY = rows[i].y0; overX = (INDENT[i] + rows[i].x1) / 2; }
      retarget();
    },
    destroy: bag.dispose,
  };
}

export const hunter = {
  name: "hunter",
  means: "A loupe drags across rows of code, magnifying the one it passes; the scan row hides a flagged line that lifts when caught.",
  rules: [1, 5, 7, 8],
  range: [40, 70, 110],
  tour: [[200, 90], [200, 130], [200, 170], [200, 220], null],
  mount,
};
