import numpy as np
from scipy.spatial import Voronoi

rng = np.random.default_rng(20260630)
W = H = 1000
PAD = 260  # generate beyond the box so edges reach the borders

# --- seed points: jittered grid so cells are irregular but evenly sized ---
def seeds(n, cell_jitter):
    step = (W + 2 * PAD) / n
    pts = []
    for i in range(n):
        for j in range(n):
            x = -PAD + step * (i + 0.5) + rng.uniform(-cell_jitter, cell_jitter) * step
            y = -PAD + step * (j + 0.5) + rng.uniform(-cell_jitter, cell_jitter) * step
            pts.append((x, y))
    return np.array(pts)

def subdivide(p, q, depth, amp):
    """Recursively roughen a segment so cracks wander instead of running straight."""
    if depth == 0:
        return [q]
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    dx, dy = q[0] - p[0], q[1] - p[1]
    L = np.hypot(dx, dy)
    if L < 1e-6:
        return [q]
    nx, ny = -dy / L, dx / L
    off = rng.normal(0, amp * L)
    m = (mx + nx * off, my + ny * off)
    return subdivide(p, m, depth - 1, amp) + subdivide(m, q, depth - 1, amp)

def edges_from(points):
    vor = Voronoi(points)
    out = []
    for (a, b) in vor.ridge_vertices:
        if a == -1 or b == -1:
            continue
        p, q = vor.vertices[a], vor.vertices[b]
        # keep ridges that could plausibly intersect the visible box
        if max(p[0], q[0]) < -40 or min(p[0], q[0]) > W + 40:
            continue
        if max(p[1], q[1]) < -40 or min(p[1], q[1]) > H + 40:
            continue
        out.append((tuple(p), tuple(q)))
    return out

def to_path(p, q, depth, amp):
    pts = subdivide(p, q, depth, amp)
    d = "M%.0f %.0f" % p
    for x, y in pts:
        d += "L%.0f %.0f" % (x, y)
    return d

layers = []
# major fissures: few, large, wide strokes
layers.append((edges_from(seeds(7, 0.34)), 4, 0.075, 3.4, 0.62))
# secondary cracks
layers.append((edges_from(seeds(13, 0.36)), 3, 0.065, 1.9, 0.44))
# hairline crazing
layers.append((edges_from(seeds(19, 0.38)), 1, 0.055, 0.9, 0.26))

parts = []
for edges, depth, amp, width, opacity in layers:
    ds = [to_path(p, q, depth, amp) for p, q in edges]
    parts.append(
        '<g stroke="#04121f" stroke-width="%.2f" stroke-opacity="%.2f" '
        'stroke-linecap="round" stroke-linejoin="round" fill="none">\n<path d="%s"/>\n</g>'
        % (width, opacity, " ".join(ds))
    )

# a few dry flakes lifting at crack junctions
flakes = []
for _ in range(90):
    cx, cy = rng.uniform(0, W), rng.uniform(0, H)
    r = rng.uniform(3, 11)
    n = rng.integers(5, 8)
    ang = np.sort(rng.uniform(0, 2 * np.pi, n))
    pts = [(cx + np.cos(a) * r * rng.uniform(0.6, 1.0),
            cy + np.sin(a) * r * rng.uniform(0.6, 1.0)) for a in ang]
    d = "M%.0f %.0f" % pts[0] + "".join("L%.0f %.0f" % p for p in pts[1:]) + "Z"
    flakes.append('<path d="%s" fill="#0a2338" fill-opacity="%.2f"/>' % (d, rng.uniform(0.10, 0.26)))

svg = '''<svg xmlns="http://www.w3.org/2000/svg" class="crack-svg" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
  <defs>
    <linearGradient id="cr-base" x1="0" y1="0" x2="0.55" y2="1">
      <stop offset="0%%" stop-color="#1d6ea8"/>
      <stop offset="42%%" stop-color="#13506f"/>
      <stop offset="100%%" stop-color="#0a2b45"/>
    </linearGradient>
    <filter id="cr-grain" x="0" y="0" width="100%%" height="100%%">
      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="4" seed="7" result="n"/>
      <feColorMatrix in="n" type="saturate" values="0"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.34"/></feComponentTransfer>
    </filter>
    <filter id="cr-mottle" x="0" y="0" width="100%%" height="100%%">
      <feTurbulence type="fractalNoise" baseFrequency="0.012" numOctaves="5" seed="3" result="n"/>
      <feColorMatrix in="n" type="saturate" values="0"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.5"/></feComponentTransfer>
    </filter>
    <radialGradient id="cr-vig" cx="0.5" cy="0.42" r="0.78">
      <stop offset="55%%" stop-color="#000" stop-opacity="0"/>
      <stop offset="100%%" stop-color="#04101c" stop-opacity="0.72"/>
    </radialGradient>
  </defs>
  <rect width="1000" height="1000" fill="url(#cr-base)"/>
  <rect width="1000" height="1000" filter="url(#cr-mottle)" opacity="0.55" style="mix-blend-mode:overlay"/>
%s
%s
  <rect width="1000" height="1000" filter="url(#cr-grain)" opacity="0.5" style="mix-blend-mode:overlay"/>
  <rect width="1000" height="1000" fill="url(#cr-vig)"/>
</svg>''' % ("\n".join(parts), "\n".join(flakes))

open("cracked-earth.svg", "w").write(svg)
print("bytes:", len(svg))
