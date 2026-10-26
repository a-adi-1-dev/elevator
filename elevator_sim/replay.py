"""Visual replay: run a simulation and write a self-contained HTML page that animates it.

    python -m elevator_sim.replay data/normal_100.csv --out replay.html --elevators 3 --floors 10
    python -m elevator_sim.replay data/normal_100.csv --out replay.html --scheduler zone --door-time 1

Takes the same options as `python -m elevator_sim`. The page needs no server or
internet connection: open it in any browser. It shows every car's floor, load
and direction tick by tick, who is waiting on each floor, and running totals.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from .building import Building
from .config import DEFAULT_MAX_TICKS, SimulationConfig
from .loader import load_requests
from .models import Direction, RuleViolationError
from .schedulers import SCHEDULERS, make_scheduler
from .simulation import Simulation


class TraceRecorder:
    """Observer that records the end-of-tick state the replay page draws."""

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self._seen_trips: set[int] = set()

    def on_tick_end(self, now: int, building: Building) -> None:
        cars = []
        for e in building.elevators:
            d = e.direction
            cars.append([
                e.current_floor,
                e.load,
                "U" if d is Direction.UP else "D" if d is Direction.DOWN else "",
                1 if e.is_holding else 0,
                len(e.assigned),
            ])
        up: dict[int, int] = {}
        down: dict[int, int] = {}
        for trip in building.waiting_trips():
            bucket = up if trip.direction is Direction.UP else down
            bucket[trip.source_floor] = bucket.get(trip.source_floor, 0) + 1
        done = [j for j in building.journeys if j.is_complete]
        waits = [j.wait_time for j in done]
        self.frames.append({
            "t": now,
            "cars": cars,
            "up": up,
            "down": down,
            "done": len(done),
            "known": len(building.journeys),
            "riding": sum(e.load for e in building.elevators),
            "avgWait": round(sum(waits) / len(waits), 2) if waits else None,
            "maxWait": max(waits) if waits else None,
        })


def build_page(title: str, meta: dict, frames: list[dict], summary: str) -> str:
    data = json.dumps({"meta": meta, "frames": frames}, separators=(",", ":"))
    return (PAGE
            .replace("__TITLE__", html.escape(title))
            .replace("__SUMMARY__", html.escape(summary))
            .replace("__DATA__", data.replace("</", "<\\/")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="elevator_sim.replay", description="Write an animated HTML replay of a run.")
    parser.add_argument("requests", help="CSV with columns time,id,source,dest")
    parser.add_argument("--out", default="replay.html", help="HTML file to write (default: %(default)s)")
    parser.add_argument("--elevators", type=int, default=3)
    parser.add_argument("--floors", type=int, help="default: the highest floor in the file")
    parser.add_argument("--capacity", type=int, default=8)
    parser.add_argument("--door-time", type=int, default=0)
    parser.add_argument("--scheduler", choices=sorted(SCHEDULERS), default="least-cost")
    parser.add_argument("--reserve-seats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    args = parser.parse_args(argv)

    try:
        passengers = load_requests(args.requests, num_floors=args.floors)
        floors = args.floors or max([2, *(max(p.source_floor, p.destination_floor) for p in passengers)])
        config = SimulationConfig(args.elevators, floors, args.capacity, args.max_ticks, args.door_time)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    recorder = TraceRecorder()
    scheduler = make_scheduler(args.scheduler, args.reserve_seats)
    failure = None
    try:
        result = Simulation(config, passengers, scheduler, [recorder]).run()
        summary = result.summary()
        if result.timed_out:
            undelivered = len(passengers) - len(result.completed)
            failure = f"stopped at --max-ticks {config.max_ticks} with {undelivered} passenger(s) not delivered"
    except RuleViolationError as e:
        summary = f"rule violation at t={e.time} ({type(e).__name__}): {e}"
        failure = summary
    label = args.scheduler + ("" if args.reserve_seats else " (no seat reservation)")
    meta = {
        "source": Path(args.requests).name,
        "scheduler": label,
        "floors": config.num_floors,
        "elevators": config.num_elevators,
        "capacity": config.capacity,
        "doorTime": config.door_time,
        "passengers": len(passengers),
    }
    page = build_page(f"Elevator replay: {meta['source']} ({label})", meta, recorder.frames, summary)
    Path(args.out).write_text(page, encoding="utf-8")
    print(summary)
    print(f"\nreplay written to {args.out} ({len(recorder.frames)} ticks)")
    if failure:
        print(f"error: {failure} (the partial replay was still written)", file=sys.stderr)
        return 1
    return 0


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --car: #2a78d6; --car-ink: #ffffff; --hold: #1c5cab;
    --up: #1baf7a; --down: #eb6834; --ring: rgba(11,11,11,0.10);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --axis: #383835; --car: #3987e5; --car-ink: #ffffff; --hold: #184f95;
      --up: #199e70; --down: #d95926; --ring: rgba(255,255,255,0.10);
    }
  }
  :root[data-theme="dark"] {
    --bg: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --car: #3987e5; --car-ink: #ffffff; --hold: #184f95;
    --up: #199e70; --down: #d95926; --ring: rgba(255,255,255,0.10);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1100px; margin: 0 auto; padding: 20px 16px 32px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: var(--ink-2); margin: 0 0 16px; }
  .layout { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 16px; align-items: start; }
  @media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
  .panel { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px; padding: 14px; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
  button, select { font: inherit; color: var(--ink); background: var(--surface); border: 1px solid var(--axis);
                   border-radius: 6px; padding: 5px 10px; cursor: pointer; }
  button:hover, select:hover { border-color: var(--muted); }
  input[type=range] { flex: 1 1 200px; accent-color: var(--car); }
  .tick { font-variant-numeric: tabular-nums; color: var(--ink-2); min-width: 92px; }
  svg { display: block; width: 100%; height: auto; max-height: calc(100vh - 150px); }
  .stat { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--grid); }
  .stat:last-of-type { border-bottom: 0; }
  .stat b { font-variant-numeric: tabular-nums; }
  .legend { color: var(--ink-2); font-size: 12px; margin-top: 10px; display: grid; gap: 4px; }
  .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
  pre { font-size: 12px; overflow-x: auto; color: var(--ink-2); margin: 0; }
  details { margin-top: 16px; }
  summary { cursor: pointer; color: var(--ink-2); }
</style>
</head>
<body>
<main>
  <h1 id="title"></h1>
  <p class="sub" id="subtitle"></p>
  <div class="layout">
    <div class="panel">
      <div class="controls">
        <button id="play" type="button">Play</button>
        <button id="back" type="button" aria-label="Previous tick">&#8592;</button>
        <button id="step" type="button" aria-label="Next tick">&#8594;</button>
        <select id="speed" aria-label="Playback speed">
          <option value="2">2 ticks/s</option>
          <option value="5" selected>5 ticks/s</option>
          <option value="10">10 ticks/s</option>
          <option value="25">25 ticks/s</option>
          <option value="60">60 ticks/s</option>
        </select>
        <input id="scrub" type="range" min="0" value="0" aria-label="Tick">
        <span class="tick" id="tick"></span>
      </div>
      <svg id="shaft" role="img" aria-label="Elevator positions"></svg>
    </div>
    <div class="panel">
      <div class="stat"><span>Delivered</span><b id="s-done"></b></div>
      <div class="stat"><span>Riding now</span><b id="s-riding"></b></div>
      <div class="stat"><span>Waiting now</span><b id="s-waiting"></b></div>
      <div class="stat"><span>Avg wait so far</span><b id="s-avg"></b></div>
      <div class="stat"><span>Longest wait so far</span><b id="s-max"></b></div>
      <div class="legend">
        <div><span class="sw" style="background:var(--car)"></span>car: number = riders aboard, arrow = heading</div>
        <div><span class="sw" style="background:var(--hold);outline:1.5px dashed var(--ink);outline-offset:-1px"></span>car holding its doors open (door time &gt; 0)</div>
        <div><span class="sw" style="background:var(--up)"></span>&#9650; waiting to go up</div>
        <div><span class="sw" style="background:var(--down)"></span>&#9660; waiting to go down</div>
      </div>
      <details>
        <summary>Final summary</summary>
        <pre>__SUMMARY__</pre>
      </details>
    </div>
  </div>
</main>
<script>
const DATA = __DATA__;
const { meta, frames } = DATA;
const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);

$("title").textContent = `Elevator replay · ${meta.scheduler}`;
$("subtitle").textContent = `${meta.source} · ${meta.passengers} passengers · ${meta.floors} floors · ` +
  `${meta.elevators} cars · capacity ${meta.capacity} · door time ${meta.doorTime}`;

// geometry
const rowH = Math.max(10, Math.min(28, Math.floor(620 / meta.floors)));
const labelW = 36, waitW = 96, carW = Math.max(28, Math.min(64, Math.floor(520 / meta.elevators))), gap = 8;
const width = labelW + waitW + meta.elevators * (carW + gap) + gap;
const height = meta.floors * rowH + 24;
const svg = $("shaft");
svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
const y = (floor) => (meta.floors - floor) * rowH + 4;
const el = (tag, attrs, parent = svg) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  parent.appendChild(n);
  return n;
};
const fontSize = Math.min(12, rowH - 2);

// static: floor lines, labels, shafts
const labelEvery = meta.floors > 40 ? 5 : meta.floors > 20 ? 2 : 1;
for (let f = 1; f <= meta.floors; f++) {
  el("line", { x1: labelW, x2: width, y1: y(f) + rowH, y2: y(f) + rowH, stroke: "var(--grid)", "stroke-width": 1 });
  if (f === 1 || f % labelEvery === 0) {
    const t = el("text", { x: labelW - 6, y: y(f) + rowH / 2 + fontSize / 3, "text-anchor": "end",
                           "font-size": fontSize, fill: "var(--muted)" });
    t.textContent = f;
  }
}
const carX = (i) => labelW + waitW + gap + i * (carW + gap);
for (let i = 0; i < meta.elevators; i++) {
  el("rect", { x: carX(i), y: 4, width: carW, height: meta.floors * rowH, fill: "none",
               stroke: "var(--grid)", "stroke-width": 1, rx: 3 });
  const t = el("text", { x: carX(i) + carW / 2, y: height - 4, "text-anchor": "middle",
                         "font-size": 11, fill: "var(--muted)" });
  t.textContent = `car ${i}`;
}

// dynamic layers
const waitLayer = el("g", {});
const cars = [];
for (let i = 0; i < meta.elevators; i++) {
  const g = el("g", {});
  const r = el("rect", { x: carX(i) + 2, width: carW - 4, height: rowH - 2, rx: 4 }, g);
  const t = el("text", { x: carX(i) + carW / 2, "text-anchor": "middle", "font-size": fontSize,
                         fill: "var(--car-ink)", "font-weight": 600 }, g);
  const title = el("title", {}, g);
  cars.push({ g, r, t, title });
}

let index = 0, playing = false, timer = null;
const scrub = $("scrub");
scrub.max = Math.max(0, frames.length - 1);

function draw(i) {
  const fr = frames[i];
  if (!fr) return;
  $("tick").textContent = `t = ${fr.t} / ${frames[frames.length - 1].t}`;
  scrub.value = i;
  fr.cars.forEach(([floor, load, dir, hold, assigned], k) => {
    const c = cars[k];
    const top = y(floor) + 1;
    c.r.setAttribute("y", top);
    c.r.setAttribute("fill", hold ? "var(--hold)" : "var(--car)");
    c.r.setAttribute("stroke", hold ? "var(--ink)" : "none");
    c.r.setAttribute("stroke-dasharray", hold ? "3 2" : "");
    c.r.setAttribute("stroke-width", hold ? 1.5 : 0);
    c.t.setAttribute("y", top + (rowH - 2) / 2 + fontSize / 3);
    const arrow = dir === "U" ? "▲" : dir === "D" ? "▼" : "";
    c.t.textContent = rowH >= 16 ? `${load}${arrow}` : `${load}`;
    c.title.textContent = `car ${k} at floor ${floor}: ${load}/${meta.capacity} aboard, ` +
      `${assigned} assigned and waiting${hold ? ", doors held open" : ""}`;
  });
  waitLayer.replaceChildren();
  let waiting = 0;
  for (const [key, color, glyph, dx] of [["up", "var(--up)", "▲", 0], ["down", "var(--down)", "▼", waitW / 2]]) {
    for (const [floor, n] of Object.entries(fr[key])) {
      waiting += n;
      const t = el("text", { x: labelW + 6 + dx, y: y(+floor) + rowH / 2 + fontSize / 3,
                             "font-size": fontSize, fill: color }, waitLayer);
      t.textContent = `${glyph} ${n}`;
    }
  }
  $("s-done").textContent = `${fr.done} / ${meta.passengers}`;
  $("s-riding").textContent = fr.riding;
  $("s-waiting").textContent = waiting;
  $("s-avg").textContent = fr.avgWait === null ? "–" : `${fr.avgWait.toFixed(1)} ticks`;
  $("s-max").textContent = fr.maxWait === null ? "–" : `${fr.maxWait} ticks`;
}

function setPlaying(on) {
  playing = on;
  $("play").textContent = on ? "Pause" : "Play";
  clearInterval(timer);
  if (on) {
    if (index >= frames.length - 1) index = 0;
    timer = setInterval(() => {
      if (index >= frames.length - 1) { setPlaying(false); return; }
      draw(++index);
    }, 1000 / +$("speed").value);
  }
}
$("play").onclick = () => setPlaying(!playing);
$("step").onclick = () => { setPlaying(false); index = Math.min(frames.length - 1, index + 1); draw(index); };
$("back").onclick = () => { setPlaying(false); index = Math.max(0, index - 1); draw(index); };
$("speed").onchange = () => { if (playing) setPlaying(true); };
scrub.oninput = () => { index = +scrub.value; draw(index); };
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "SELECT") return;
  if (e.key === " ") { e.preventDefault(); setPlaying(!playing); }
  if (e.key === "ArrowRight") $("step").click();
  if (e.key === "ArrowLeft") $("back").click();
});
draw(0);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
