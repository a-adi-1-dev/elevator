import io
import unittest

from elevator_sim import (
    NearestCarScheduler, Passenger, PositionLogWriter, Scheduler, Simulation, SimulationConfig, Stats,
    percentile,
)


class OneCarFifo(Scheduler):
    def assign(self, now, passenger, building):
        car = building.elevators[0]
        car.add_stop(passenger.source_floor)
        car.add_stop(passenger.destination_floor)
        return car


class PositionLogWriterTest(unittest.TestCase):
    def test_one_row_per_tick_with_every_elevator(self):
        out = io.StringIO()
        config = SimulationConfig(num_elevators=2, num_floors=10, capacity=4)
        recorder = PositionLogWriter(out, config.num_elevators)
        result = Simulation(config, [Passenger("a", 1, 3, 0)], OneCarFifo(), [recorder]).run()

        rows = out.getvalue().splitlines()
        self.assertEqual(rows[0], "time,elevator_0,elevator_1")
        self.assertEqual(rows[1:], ["0,1,1", "1,2,1", "2,3,1"])
        self.assertEqual(len(rows) - 1, result.ticks)

    def test_empty_run_writes_header_only(self):
        out = io.StringIO()
        config = SimulationConfig(num_elevators=1, num_floors=5, capacity=1)
        Simulation(config, [], NearestCarScheduler(), [PositionLogWriter(out, 1)]).run()
        self.assertEqual(out.getvalue().splitlines(), ["time,elevator_0"])


class StatsTest(unittest.TestCase):
    def test_of(self):
        self.assertEqual(Stats.of([4, 1, 7]), Stats(3, 1, 7, 4, 4, 7))
        self.assertIsNone(Stats.of([]))

    def test_percentile_is_nearest_rank(self):
        data = list(range(1, 21))  # 1..20
        self.assertEqual(percentile(data, 50), 10)
        self.assertEqual(percentile(data, 95), 19)
        self.assertEqual(percentile(data, 100), 20)
        self.assertEqual(percentile([5], 95), 5)

    def test_result_stats_cover_completed_trips(self):
        # a: 1 -> 3 at t=0, picked up 0, arrives 2.  b: 5 -> 4 at t=0, picked up 4, arrives 5.
        config = SimulationConfig(num_elevators=1, num_floors=10, capacity=4)
        passengers = [Passenger("a", 1, 3, 0), Passenger("b", 5, 4, 0)]
        result = Simulation(config, passengers, OneCarFifo()).run()
        self.assertEqual(result.wait_stats, Stats(2, 0, 4, 2, 0, 4))
        self.assertEqual(result.total_stats, Stats(2, 2, 5, 3.5, 2, 5))
        self.assertEqual(result.travel_stats, Stats(2, 1, 2, 1.5, 1, 2))
        self.assertEqual(result.longest_wait.passenger.passenger_id, "b")
        summary = result.summary()
        for text in ("wait time", "travel time", "total time", "longest wait : b waited 4 ticks"):
            self.assertIn(text, summary)

    def test_elevator_stats(self):
        config = SimulationConfig(num_elevators=1, num_floors=10, capacity=4)
        passengers = [Passenger("a", 1, 3, 0), Passenger("b", 5, 4, 0)]
        (e,) = Simulation(config, passengers, OneCarFifo()).run().elevators
        # 1 -> 3 -> 5 -> 4: 5 floors; stops at 1 (a on), 3 (a off), 5 (b on), 4 (b off)
        self.assertEqual((e.floors_travelled, e.stops, e.passengers_carried, e.peak_load), (5, 4, 2, 1))

    def test_summary_without_completions(self):
        config = SimulationConfig(num_elevators=1, num_floors=10, capacity=1, max_ticks=3)
        result = Simulation(config, [Passenger("a", 1, 9, 0)], OneCarFifo()).run()
        self.assertIsNone(result.wait_stats)
        self.assertIn("incomplete      : 1", result.summary())
        self.assertIn("no completed trips", result.summary())


if __name__ == "__main__":
    unittest.main()
