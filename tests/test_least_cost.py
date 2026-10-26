import unittest

from elevator_sim import Elevator, ElevatorTrip, Passenger, RideRequest
from elevator_sim.schedulers.least_cost import marginal_cost


def ride(pid, source, dest, time=0):
    return RideRequest.direct(Passenger(pid, source, dest, time))


class MarginalCostTest(unittest.TestCase):
    def test_prices_the_delay_to_riders(self):
        # Car A: three riders 1 -> 10 just boarded (doors held 2 more ticks). Car B: empty. Both at floor 1.
        a = Elevator(0, capacity=8, num_floors=10, door_time=2)
        for i in range(3):
            trip = ElevatorTrip(ride(f"r{i}", 1, 10), 0)
            a.accept(trip)
            a.board(trip, 0)
        b = Elevator(1, capacity=8, num_floors=10, door_time=2)
        new = ride("n", 3, 9)

        # A without n: riders arrive at 2 (hold) + 9 = 11 -> 33.
        # A with n: stops 3 (t=4), 9 (t=4+2+6=12), 10 (t=12+2+1=15): riders 3*15 + n 12 = 57.
        self.assertEqual(marginal_cost(a, new), 57 - 33)
        # B: to floor 3 (t=2), doors 2, to 9 (t=10).
        self.assertEqual(marginal_cost(b, new), 10)


if __name__ == "__main__":
    unittest.main()
