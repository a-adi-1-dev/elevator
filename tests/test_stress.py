"""Randomized stress test: every scheduler, many random buildings and traffic patterns.

For each run it checks the brief's three objectives hold:
  * every passenger is eventually delivered (no starvation, no timeout)
  * elevator rules are honoured (any violation raises and fails the test)
  * capacity is never exceeded
plus some timing identities that catch bookkeeping bugs.

Default is a quick run. For a long one:

    STRESS_RUNS=5000 python -m unittest tests.test_stress
"""

import os
import random
import unittest

from elevator_sim import Passenger, Simulation, SimulationConfig
from elevator_sim.schedulers import SCHEDULERS, make_scheduler

RUNS = int(os.environ.get("STRESS_RUNS", "25"))
SEED = int(os.environ.get("STRESS_SEED", "2026"))


def random_scenario(rng: random.Random) -> tuple[SimulationConfig, list[Passenger]]:
    floors = rng.randint(2, 40)
    config = SimulationConfig(
        num_elevators=rng.randint(1, 10),
        num_floors=floors,
        capacity=rng.randint(1, 10),
        door_time=rng.choice((0, 0, 0, 1, 2, 3)),
        max_ticks=200_000,
    )
    count = rng.randint(0, 120)
    span = rng.choice((1, 5, 50, 300))  # 1 = everyone at once (a burst)
    lobby_bias = rng.random()
    passengers = []
    for i in range(count):
        if rng.random() < lobby_bias:
            upper = rng.randint(2, floors)
            source, dest = (1, upper) if rng.random() < 0.5 else (upper, 1)
        else:
            source, dest = rng.sample(range(1, floors + 1), 2)
        passengers.append(Passenger(f"p{i}", source, dest, rng.randrange(span)))
    return config, passengers


class StressTest(unittest.TestCase):
    def test_random_runs(self):
        rng = random.Random(SEED)
        for run in range(RUNS):
            config, passengers = random_scenario(rng)
            reserve = rng.random() < 0.5
            for name in SCHEDULERS:
                with self.subTest(run=run, scheduler=name, reserve=reserve, config=config, n=len(passengers)):
                    result = Simulation(config, passengers, make_scheduler(name, reserve)).run()
                    self.assertFalse(result.timed_out)
                    self.assertEqual(len(result.completed), len(passengers))
                    for e in result.elevators:
                        self.assertLessEqual(e.peak_load, config.capacity)
                    for j in result.journeys:
                        p = j.passenger
                        travel = j.total_time - j.wait_time
                        self.assertGreaterEqual(j.wait_time, 0)
                        self.assertGreaterEqual(travel, p.distance)
                        if config.door_time == 0 and j.transfers == 0:
                            # stops are free and a loaded car never turns back: ride = distance
                            self.assertEqual(travel, p.distance)


if __name__ == "__main__":
    unittest.main()
