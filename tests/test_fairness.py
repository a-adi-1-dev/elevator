import unittest

from elevator_sim import NearestCarScheduler, Passenger, Simulation, SimulationConfig
from elevator_sim.schedulers import SCHEDULERS, make_scheduler


def stream_with_one_midfloor_passenger(stream_length):
    """One car, one seat. A steady stream of lobby -> top trips, and one person on floor 5
    going up who asked first. The car fills at the lobby every time it comes back."""
    return [Passenger("mid", 5, 6, 0)] + [Passenger(f"s{i}", 1, 10, 2 * i) for i in range(stream_length)]


def mid_wait(scheduler, stream_length):
    config = SimulationConfig(num_elevators=1, num_floors=10, capacity=1)
    result = Simulation(config, stream_with_one_midfloor_passenger(stream_length), scheduler).run()
    return next(j.wait_time for j in result.journeys if j.passenger.passenger_id == "mid")


class StarvationTest(unittest.TestCase):
    def test_plain_nearest_car_starves_the_midfloor_passenger(self):
        # Their wait grows with the stream: with an endless stream they would never be served.
        plain = lambda: make_scheduler("nearest-car", reserve_seats=False)  # noqa: E731
        short, long = mid_wait(plain(), 20), mid_wait(plain(), 60)
        self.assertGreater(long, short + 500)

    def test_seat_reservation_bounds_the_wait(self):
        # s0 asked at the same tick, so it is not newer and rides first; on the
        # next upward sweep the car keeps its seat for "mid": 18 ticks round trip + 4 floors.
        for stream_length in (20, 40, 60):
            with self.subTest(stream_length=stream_length):
                self.assertEqual(mid_wait(make_scheduler("nearest-car", reserve_seats=True), stream_length), 22)

    def test_reservation_is_on_by_default(self):
        self.assertTrue(NearestCarScheduler().reserve_seats_for_older)
        self.assertTrue(make_scheduler("least-cost").reserve_seats_for_older)
        self.assertEqual(mid_wait(NearestCarScheduler(), 60), 22)

    def test_every_scheduler_is_bounded_with_reservation(self):
        for name in SCHEDULERS:
            with self.subTest(name):
                short = mid_wait(make_scheduler(name, True), 20)
                long = mid_wait(make_scheduler(name, True), 60)
                self.assertEqual(short, long)


if __name__ == "__main__":
    unittest.main()
