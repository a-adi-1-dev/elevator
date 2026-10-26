import unittest

from elevator_sim import (
    Direction, DirectionViolationError, Elevator, ElevatorTrip, Passenger, RideRequest, SimulationConfig,
    SkipViolationError, StallViolationError, TripStatus,
)
from elevator_sim.feed import RequestFeed
from elevator_sim.models import InvalidTransitionError


class RequestFeedTest(unittest.TestCase):
    def test_releases_only_due_requests(self):
        feed = RequestFeed([Passenger("b", 1, 2, 3), Passenger("a", 1, 2, 0)])
        self.assertEqual([p.passenger_id for p in feed.release(0)], ["a"])
        self.assertEqual(feed.release(1), [])
        self.assertEqual(feed.release(2), [])
        self.assertFalse(feed.is_exhausted)
        self.assertEqual([p.passenger_id for p in feed.release(3)], ["b"])
        self.assertTrue(feed.is_exhausted)

    def test_clock_cannot_go_backwards(self):
        feed = RequestFeed([])
        feed.release(5)
        with self.assertRaises(ValueError):
            feed.release(4)


class ElevatorTripTest(unittest.TestCase):
    def test_lifecycle_and_metrics(self):
        trip = ElevatorTrip(RideRequest.direct(Passenger("a", 2, 6, request_time=10)), elevator_id=0)
        self.assertIs(trip.status, TripStatus.ASSIGNED)
        trip.board(0, now=13)
        trip.alight(now=17)
        self.assertIs(trip.status, TripStatus.COMPLETED)
        self.assertEqual((trip.wait_time, trip.ride_time, trip.total_time), (3, 4, 7))

    def test_cannot_be_created_unassigned(self):
        with self.assertRaises(TypeError):
            ElevatorTrip(RideRequest.direct(Passenger("a", 2, 6, 0)))

    def test_cannot_board_someone_elses_elevator(self):
        trip = ElevatorTrip(RideRequest.direct(Passenger("a", 2, 6, 0)), elevator_id=0)
        with self.assertRaises(InvalidTransitionError):
            trip.board(1, now=0)

    def test_cannot_alight_before_boarding(self):
        with self.assertRaises(InvalidTransitionError):
            ElevatorTrip(RideRequest.direct(Passenger("a", 2, 6, 0)), elevator_id=0).alight(now=0)


class ElevatorTest(unittest.TestCase):
    def test_moves_one_floor_per_tick_and_opens_at_stop(self):
        e = Elevator(0, capacity=2, num_floors=10)
        e.add_stop(3)
        self.assertIs(e.direction, Direction.UP)
        e.move()
        self.assertEqual((e.current_floor, e.open_doors()), (2, False))
        e.move()
        self.assertEqual((e.current_floor, e.open_doors()), (3, True))
        self.assertTrue(e.is_idle)
        e.move()
        self.assertEqual(e.current_floor, 3)

    def test_add_stop_keeps_revisits_but_drops_immediate_repeats(self):
        e = Elevator(0, capacity=2, num_floors=10)
        for floor in (5, 5, 1, 5):
            e.add_stop(floor)
        self.assertEqual(e.stops, (5, 1, 5))

    def test_enforces_capacity_and_floor(self):
        e = Elevator(0, capacity=1, num_floors=10)
        e.board(give(e, "a", 1, 5), now=0)
        with self.assertRaises(RuntimeError):
            e.board(give(e, "b", 1, 5), now=0)
        with self.assertRaises(ValueError):
            e.add_stop(11)

    def test_only_assigned_passengers_can_board(self):
        e = Elevator(0, capacity=4, num_floors=10)
        with self.assertRaises(RuntimeError):
            e.board(ElevatorTrip(RideRequest.direct(Passenger("a", 1, 5, 0)), 0), now=0)

    def test_unload_only_riders_for_this_floor(self):
        e = Elevator(0, capacity=4, num_floors=10)
        e.board(give(e, "a", 1, 2), now=0)
        e.board(give(e, "b", 1, 3), now=0)
        e.add_stop(2)
        e.move()
        self.assertEqual([t.passenger_id for t in e.unload(now=1)], ["a"])
        self.assertEqual(e.load, 1)


def give(e, passenger_id, source, destination):
    """Assign a new trip to elevator `e` and return it (passenger still waiting)."""
    trip = ElevatorTrip(RideRequest.direct(Passenger(passenger_id, source, destination, 0)), e.elevator_id)
    e.accept(trip)
    return trip


def car_carrying(source, destination, stops, capacity=4):
    e = Elevator(0, capacity=capacity, num_floors=10, start_floor=source)
    e.board(give(e, "r", source, destination), now=0)
    e.set_stops(stops)
    return e


def run_ticks(e, n):
    for _ in range(n):
        e.move()
        e.open_doors()


class DirectionLockTest(unittest.TestCase):
    def test_cannot_reverse_with_rider_going_current_way(self):
        e = car_carrying(1, 5, [3, 2])  # rider wants up to 5; plan turns back at 3
        run_ticks(e, 2)
        self.assertEqual((e.current_floor, e.direction), (3, Direction.UP))
        self.assertTrue(e.is_direction_locked)
        self.assertFalse(e.can_move_toward(2))
        with self.assertRaises(DirectionViolationError):
            e.move()

    def test_may_reverse_once_those_riders_are_dropped(self):
        e = car_carrying(1, 3, [3, 2])
        run_ticks(e, 2)
        e.unload(now=2)
        self.assertFalse(e.is_direction_locked)
        e.move()
        self.assertEqual((e.current_floor, e.direction), (2, Direction.IDLE))

    def test_clearing_stops_does_not_release_the_lock(self):
        e = car_carrying(1, 5, [3])
        run_ticks(e, 2)
        e.clear_stops()
        self.assertIs(e.direction, Direction.UP)
        e.set_stops([1])
        with self.assertRaises(DirectionViolationError):
            e.move()

    def test_assigned_passenger_ahead_going_same_way_locks(self):
        e = Elevator(0, capacity=4, num_floors=10)
        e.set_stops([3])
        waiting = give(e, "w", 6, 9)
        run_ticks(e, 2)  # empty car now at 3, heading up; "w" is waiting above, going up
        self.assertEqual(e.locking_trips, (waiting,))
        e.set_stops([1])
        with self.assertRaises(DirectionViolationError):
            e.move()

    def test_assigned_passengers_behind_or_going_other_way_do_not_lock(self):
        e = Elevator(0, capacity=4, num_floors=10)
        e.set_stops([3])
        run_ticks(e, 2)
        give(e, "behind", 2, 9)
        give(e, "opposite", 6, 2)
        self.assertFalse(e.is_direction_locked)
        e.set_stops([2])
        e.move()
        self.assertEqual(e.current_floor, 2)


class BoardingDirectionTest(unittest.TestCase):
    def test_locked_car_refuses_passenger_going_the_other_way(self):
        e = car_carrying(1, 5, [3, 5])
        run_ticks(e, 2)
        down = give(e, "d", 3, 1)
        self.assertFalse(e.can_board(down))
        with self.assertRaises(DirectionViolationError):
            e.board(down, now=2)

    def test_boarding_an_unlocked_car_commits_it_to_that_direction(self):
        e = Elevator(0, capacity=4, num_floors=10)
        e.set_stops([3, 5])
        run_ticks(e, 2)  # empty car at 3, was heading up
        e.board(give(e, "d", 3, 1), now=2)
        self.assertIs(e.direction, Direction.DOWN)
        with self.assertRaises(DirectionViolationError):
            e.move()  # next stop 5 is now the wrong way


class NoSkippingTest(unittest.TestCase):
    def test_cannot_carry_rider_past_destination(self):
        e = car_carrying(1, 3, [5])
        run_ticks(e, 2)
        with self.assertRaises(SkipViolationError):
            e.move()

    def test_cannot_pass_assigned_passenger_going_same_way(self):
        e = Elevator(0, capacity=4, num_floors=10)
        e.set_stops([5])
        give(e, "w", 2, 6)
        run_ticks(e, 1)
        with self.assertRaises(SkipViolationError):
            e.move()

    def test_full_car_may_pass(self):
        e = car_carrying(1, 6, [6], capacity=1)
        give(e, "w", 2, 7)
        run_ticks(e, 2)
        self.assertEqual(e.current_floor, 3)

    def test_may_pass_passenger_going_the_other_way(self):
        e = Elevator(0, capacity=4, num_floors=10)
        e.set_stops([5, 2])
        give(e, "d", 2, 1)
        run_ticks(e, 2)
        self.assertEqual(e.current_floor, 3)


class NoSittingStillTest(unittest.TestCase):
    def test_car_with_waiting_assignment_must_move(self):
        e = Elevator(0, capacity=4, num_floors=10)
        give(e, "w", 5, 7)
        with self.assertRaises(StallViolationError):
            e.move()

    def test_car_with_rider_must_move(self):
        e = car_carrying(1, 5, [])
        with self.assertRaises(StallViolationError):
            e.move()

    def test_car_without_work_may_idle(self):
        e = Elevator(0, capacity=4, num_floors=10)
        e.move()
        self.assertEqual(e.current_floor, 1)


class SimulationConfigTest(unittest.TestCase):
    def test_bounds(self):
        SimulationConfig(num_elevators=10, num_floors=2, capacity=1)
        for kwargs in ({"num_elevators": 0}, {"num_elevators": 11}, {"num_floors": 1}, {"capacity": 0}):
            params = {"num_elevators": 1, "num_floors": 10, "capacity": 4, **kwargs}
            with self.subTest(kwargs), self.assertRaises(ValueError):
                SimulationConfig(**params)


if __name__ == "__main__":
    unittest.main()
