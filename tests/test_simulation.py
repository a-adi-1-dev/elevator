import unittest

from elevator_sim import (
    DirectionViolationError, Elevator, NaiveScheduler, NearestCarScheduler, Passenger, Scheduler, Simulation,
    SimulationConfig, StallViolationError, TripStatus,
)


class FifoSingleCarScheduler(Scheduler):
    """Test double only: sends elevator 0 to each request's source then destination, in order."""

    def __init__(self):
        self.seen_at = {}
        self.seen_on_tick = []

    def assign(self, now, passenger, building):
        self.seen_at[passenger.passenger_id] = now
        car = building.elevators[0]
        car.add_stop(passenger.source_floor)
        car.add_stop(passenger.destination_floor)
        return car

    def on_tick(self, now, new_trips, building):
        self.seen_on_tick += [(t.passenger_id, t.elevator_id, t.status) for t in new_trips]


class RogueScheduler(Scheduler):
    def assign(self, now, passenger, building):
        return Elevator(99, capacity=1, num_floors=building.num_floors)


class SimulationTest(unittest.TestCase):
    def config(self, **kwargs):
        return SimulationConfig(**{"num_elevators": 1, "num_floors": 10, "capacity": 4, **kwargs})

    def test_requests_reach_scheduler_exactly_at_their_time(self):
        scheduler = FifoSingleCarScheduler()
        passengers = [Passenger("late", 2, 1, 7), Passenger("early", 1, 2, 0)]
        Simulation(self.config(), passengers, scheduler).run()
        self.assertEqual(scheduler.seen_at, {"early": 0, "late": 7})

    def test_trips_are_assigned_the_moment_they_are_released(self):
        scheduler = FifoSingleCarScheduler()
        Simulation(self.config(), [Passenger("a", 1, 3, 0), Passenger("b", 4, 2, 0)], scheduler).run()
        # "a" boarded the idle car during the doors phase, before on_tick; "b" is still waiting.
        self.assertEqual(scheduler.seen_on_tick, [("a", 0, TripStatus.RIDING), ("b", 0, TripStatus.ASSIGNED)])

    def test_assignment_must_be_an_elevator_in_the_building(self):
        with self.assertRaises(RuntimeError):
            Simulation(self.config(), [Passenger("a", 1, 2, 0)], RogueScheduler()).run()

    def test_assign_is_mandatory_for_schedulers(self):
        class NoAssign(Scheduler):
            pass

        with self.assertRaises(TypeError):
            NoAssign()

    def test_single_ride_timing(self):
        # Car starts at floor 1. Request at t=2 from floor 1 to floor 4:
        # board at t=2 (car already there), then 3 floors = 3 ticks.
        result = Simulation(self.config(), [Passenger("a", 1, 4, 2)], FifoSingleCarScheduler()).run()
        (trip,) = result.trips
        self.assertFalse(result.timed_out)
        self.assertIs(trip.status, TripStatus.COMPLETED)
        self.assertEqual((trip.pickup_time, trip.dropoff_time), (2, 5))
        self.assertEqual((trip.wait_time, trip.ride_time), (0, 3))

    def test_pickup_requires_travel(self):
        # Car must travel 1 -> 5 (4 ticks) to pick up, then 5 -> 3 (2 ticks).
        result = Simulation(self.config(), [Passenger("a", 5, 3, 0)], FifoSingleCarScheduler()).run()
        (trip,) = result.trips
        self.assertEqual((trip.pickup_time, trip.dropoff_time), (4, 6))

    def test_intermediate_stops_cost_no_time(self):
        # "a" rides 1 -> 8. The car also stops at 3 (drop off "b") and 5 (pick up "c")
        # on the way, yet "a" arrives at t=7 - the same as a nonstop 7-floor ride.
        passengers = [Passenger("a", 1, 8, 0), Passenger("b", 1, 3, 0), Passenger("c", 5, 8, 0)]

        class Sweep(Scheduler):
            def assign(self, now, passenger, building):
                return building.elevators[0]

            def on_tick(self, now, new_trips, building):
                # "a" and "b" already boarded at t=0 through the idle car's open doors.
                if new_trips:
                    building.elevators[0].set_stops([3, 5, 8])

        result = Simulation(self.config(), passengers, Sweep()).run()
        trips = {t.passenger_id: t for t in result.trips}
        self.assertEqual((trips["a"].pickup_time, trips["a"].dropoff_time), (0, 7))
        self.assertEqual(trips["b"].dropoff_time, 2)
        self.assertEqual((trips["c"].pickup_time, trips["c"].dropoff_time), (4, 7))

    def test_dropoff_and_pickup_at_same_floor_same_tick(self):
        # Car carries "a" 1 -> 4; "b" waits at 4 going to 2. Both happen at t=3,
        # and the car is already one floor down at t=4.
        passengers = [Passenger("a", 1, 4, 0), Passenger("b", 4, 2, 0)]
        result = Simulation(self.config(), passengers, FifoSingleCarScheduler()).run()
        trips = {t.passenger_id: t for t in result.trips}
        self.assertEqual(trips["a"].dropoff_time, 3)
        self.assertEqual((trips["b"].pickup_time, trips["b"].dropoff_time), (3, 5))

    def test_scheduler_that_reverses_with_riders_aboard_is_rejected(self):
        # "a" rides 1 -> 6. At t=2 (car at floor 3), "b" calls from 2. A greedy
        # scheduler that serves the newest call first would turn the car around.
        class GreedyNewestFirst(Scheduler):
            def assign(self, now, passenger, building):
                car = building.elevators[0]
                car.set_stops([passenger.source_floor, passenger.destination_floor, *car.stops])
                return car

        passengers = [Passenger("a", 1, 6, 0), Passenger("b", 2, 1, 2)]
        with self.assertRaises(DirectionViolationError):
            Simulation(self.config(), passengers, GreedyNewestFirst()).run()

    def test_car_with_work_left_without_stops_stalls_and_violation_is_timestamped(self):
        class NeverPlans(Scheduler):
            def assign(self, now, passenger, building):
                return building.elevators[0]

        # "a" boards the idle car at t=0; at t=1 the car has a rider but no stop.
        with self.assertRaises(StallViolationError) as ctx:
            Simulation(self.config(), [Passenger("a", 1, 2, 0)], NeverPlans()).run()
        self.assertEqual(ctx.exception.time, 1)

    def test_hits_max_ticks(self):
        result = Simulation(self.config(max_ticks=3), [Passenger("a", 1, 9, 0)], FifoSingleCarScheduler()).run()
        self.assertTrue(result.timed_out)
        self.assertEqual(result.ticks, 3)
        self.assertEqual(result.completed, ())

    def test_default_boarding_only_takes_passengers_going_the_cars_way(self):
        # Car carries "up" 1 -> 6. "down" (4 -> 1) is assigned to it too; the car
        # stops at 4 for "same" (4 -> 6) but must leave "down" there.
        class Plan(Scheduler):
            def assign(self, now, passenger, building):
                building.elevators[0].set_stops([1, 4, 6, 4, 1])
                return building.elevators[0]

        passengers = [Passenger("up", 1, 6, 0), Passenger("same", 4, 6, 0), Passenger("down", 4, 1, 0)]
        result = Simulation(self.config(), passengers, Plan()).run()
        trips = {t.passenger_id: t for t in result.trips}
        self.assertEqual(trips["same"].pickup_time, 3)
        self.assertEqual((trips["down"].pickup_time, trips["down"].dropoff_time), (7, 10))

    def test_no_requests_finishes_immediately(self):
        result = Simulation(self.config(), [], NearestCarScheduler()).run()
        self.assertEqual((result.ticks, result.timed_out), (0, False))



class DoorTimeTest(unittest.TestCase):
    def run_one(self, passengers, door_time, scheduler=None, elevators=1):
        config = SimulationConfig(num_elevators=elevators, num_floors=10, capacity=4, door_time=door_time)
        return Simulation(config, passengers, scheduler or NearestCarScheduler()).run()

    def test_zero_door_time_stops_are_free(self):
        (j,) = self.run_one([Passenger("a", 1, 4, 0)], door_time=0).journeys
        self.assertEqual((j.wait_time, j.total_time), (0, 3))

    def test_each_stop_holds_the_car(self):
        # Boards at t=0, doors held t=1..2, then 3 floors: arrives at t=5.
        (j,) = self.run_one([Passenger("a", 1, 4, 0)], door_time=2).journeys
        self.assertEqual((j.wait_time, j.total_time), (0, 5))

    def test_intermediate_stop_delays_riders(self):
        # b gets on at floor 2 on a's way up: a's ride is held there for 1 tick.
        result = self.run_one([Passenger("a", 1, 5, 0), Passenger("b", 2, 4, 0)], door_time=1)
        times = {j.passenger.passenger_id: j.total_time for j in result.journeys}
        # a: board t0, hold t1, floor 2 at t2 (b boards), hold t3, floor 3 t4, floor 4 t5 (b off), hold t6, floor 5 t7
        self.assertEqual(times, {"a": 7, "b": 5 - 0})

    def test_late_arrival_boards_while_doors_are_held(self):
        # Naive does not re-plan for p2, but the doors are still open at floor 1 at t=1.
        result = self.run_one(
            [Passenger("p1", 1, 3, 0), Passenger("p2", 1, 5, 1)], door_time=2, scheduler=NaiveScheduler()
        )
        pickup = {t.passenger_id: t.pickup_time for t in result.trips}
        self.assertEqual(pickup, {"p1": 0, "p2": 1})


if __name__ == "__main__":
    unittest.main()
