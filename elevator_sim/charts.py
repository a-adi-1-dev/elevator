"""Charts for the experiment results (matplotlib, optional dependency).

Each scheduler keeps the same color in every chart, and every chart has a
legend and value labels.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, NullLocator, ScalarFormatter  # noqa: E402

COLORS = {"least-cost": "#2a78d6", "nearest-car": "#eb6834", "zone": "#1baf7a", "naive": "#eda100"}
BAR_ORDER = ["least-cost", "nearest-car", "zone", "naive"]
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
TRAFFIC_ORDER = ["up-peak", "down-peak", "mixed", "random"]

plt.rcParams.update({
    "font.family": ["DejaVu Sans"],
    "font.size": 10,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.grid": True,
    "axes.grid.axis": "y",
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2,
    "ytick.left": False,
    "legend.frameon": False,
    "legend.labelcolor": INK_2,
    "lines.linewidth": 2,
    "lines.markersize": 6,
})


def _finish(fig, title: str, subtitle: str, path: Path) -> Path:
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK, y=0.985)
    fig.text(0.01, 0.925, subtitle, ha="left", va="top", fontsize=9.5, color=INK_2)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path


def schedulers_chart(rows: list[dict], out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6), sharey=True)
    width = 0.2
    for ax, door_time in zip(axes, (0, 2)):
        for i, name in enumerate(BAR_ORDER):
            values = [next(r["total_avg"] for r in rows
                           if r["traffic"] == t and r["scheduler"] == name and r["door_time"] == door_time)
                      for t in TRAFFIC_ORDER]
            xs = [x + (i - 1.5) * width for x in range(len(TRAFFIC_ORDER))]
            bars = ax.bar(xs, values, width * 0.9, color=COLORS[name], label=name, zorder=2)
            ax.bar_label(bars, fmt="%.0f", fontsize=7.5, color=INK_2, padding=2)
        ax.set_xticks(range(len(TRAFFIC_ORDER)), TRAFFIC_ORDER)
        ax.tick_params(axis="x", length=0)
        ax.set_title("free stops (the brief's model)" if door_time == 0 else "doors take 2 ticks per stop",
                     loc="left")
    axes[0].set_ylabel("average total time per passenger (ticks)")
    axes[1].legend(loc="upper right", ncols=2, fontsize=9)
    return _finish(fig, "Least-cost is fastest for every traffic pattern, except up-peak with slow doors, where zoning wins",
                   "600 passengers over 600 ticks · 20 floors · 4 cars · capacity 10 · mean of all seeds · "
                   "lower is better", out / "schedulers.png")


def _line(ax, xs, ys, name, style="-", label=None, end_label=True):
    ax.plot(xs, ys, style, color=COLORS[name], marker="o", label=label or name, zorder=3,
            markeredgecolor=SURFACE, markeredgewidth=1.5)
    if end_label:
        ax.annotate(label or name, (xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK_2)


def fleet_chart(rows: list[dict], out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4))
    for ax, metric, title in zip(axes, ("total_avg", "total_p95"),
                                 ("average total time", "95th-percentile total time")):
        for name in ("least-cost", "nearest-car"):
            pts = sorted((r["elevators"], r[metric]) for r in rows if r["scheduler"] == name)
            _line(ax, [p[0] for p in pts], [p[1] for p in pts], name, end_label=False)
        ax.set_yscale("log")
        lo = min(r[metric] for r in rows)
        hi = max(r[metric] for r in rows)
        ticks = [t for t in (10, 15, 20, 30, 50, 100, 200, 300, 500, 1000) if lo * 0.8 <= t <= hi * 1.25]
        ax.yaxis.set_major_locator(FixedLocator(ticks))
        ax.yaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_major_formatter(ScalarFormatter())
        ax.set_xticks(range(1, 11))
        ax.set_xlim(0.6, 10.4)
        ax.set_xlabel("number of cars")
        ax.set_title(title + " (ticks, log scale)", loc="left")
        ax.grid(True, which="major", axis="both", color=GRID, linewidth=0.6)
    axes[0].legend(loc="upper right")
    return _finish(fig, "Past 4-5 cars, extra cars buy little; least-cost helps most when the fleet is short",
                   "mixed traffic · 600 passengers over 600 ticks · 20 floors · capacity 10 · free stops",
                   out / "fleet.png")


def door_time_chart(rows: list[dict], out: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    for name in ("zone", "least-cost", "nearest-car"):
        pts = sorted((r["door_time"], r["total_avg"]) for r in rows if r["scheduler"] == name)
        _line(ax, [p[0] for p in pts], [p[1] for p in pts], name)
    ax.set_xticks(sorted({r["door_time"] for r in rows}))
    ax.set_xlim(-0.2, max(r["door_time"] for r in rows) + 0.9)
    ax.set_xlabel("ticks the doors stay open at each stop")
    ax.set_ylabel("average total time per passenger (ticks)")
    ax.legend(loc="upper left")
    return _finish(fig, "In a tall building at up-peak, zoning overtakes once each stop costs about 2 ticks",
                   "up-peak · 300 passengers over 600 ticks · 40 floors · 4 cars · capacity 10",
                   out / "door_time.png")


def fairness_chart(rows: list[dict], out: Path) -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4))
    for ax, metric, title in zip(axes, ("wait_max", "total_avg"),
                                 ("worst wait (ticks)", "average total time (ticks)")):
        for name in ("least-cost", "nearest-car"):
            for reserve, style in ((False, "-"), (True, "--")):
                pts = sorted((r["passengers"], r[metric]) for r in rows
                             if r["scheduler"] == name and r["reserve_seats"] is reserve)
                label = f"{name} + reserve seats" if reserve else name
                _line(ax, [p[0] for p in pts], [p[1] for p in pts], name, style, label, end_label=False)
        ax.set_xticks(sorted({r["passengers"] for r in rows}))
        ax.set_xlabel("passengers over 600 ticks")
        ax.set_title(title, loc="left")
    axes[0].legend(loc="upper left", fontsize=9)
    return _finish(fig, "Seat reservation cuts the worst wait, at a cost to the average once the building is busy",
                   "mixed traffic · 20 floors · 4 cars · capacity 4 (so cars fill up) · dashed = reservation on",
                   out / "fairness.png")


def draw_all(sched, fleet, door, fair, out: Path) -> list[Path]:
    out = Path(out)
    return [schedulers_chart(sched, out), fleet_chart(fleet, out), door_time_chart(door, out),
            fairness_chart(fair, out)]
