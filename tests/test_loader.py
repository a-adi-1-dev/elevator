import io
import unittest

from elevator_sim import RequestFileError, read_requests


def parse(text, num_floors=10):
    return read_requests(io.StringIO(text), num_floors)


class ReadRequestsTest(unittest.TestCase):
    def test_parses_and_sorts_by_time_stably(self):
        passengers = parse(
            "time,passenger_id,source,destination\n"
            "5,a,1,3\n"
            "0,b,4,2\n"
            "5,c,2,9\n"
        )
        self.assertEqual([p.passenger_id for p in passengers], ["b", "a", "c"])
        self.assertEqual(passengers[0].source_floor, 4)
        self.assertEqual(passengers[0].destination_floor, 2)

    def test_tolerates_whitespace_and_extra_columns(self):
        (p,) = parse(" time , passenger_id , source , destination , note\n 1 , x , 2 , 3 , hi\n")
        self.assertEqual((p.request_time, p.passenger_id, p.source_floor, p.destination_floor), (1, "x", 2, 3))

    def test_accepts_the_briefs_header(self):
        passengers = parse(
            "time,id,source,dest\n0,passenger1,1,51\n0,passenger2,1,37\n10,passenger3,20,1\n",
            num_floors=60,
        )
        self.assertEqual([p.passenger_id for p in passengers], ["passenger1", "passenger2", "passenger3"])
        self.assertEqual((passengers[2].source_floor, passengers[2].destination_floor), (20, 1))

    def test_header_is_case_insensitive(self):
        (p,) = parse("Time,ID,Source,Dest\n3,a,2,5\n")
        self.assertEqual((p.request_time, p.source_floor, p.destination_floor), (3, 2, 5))

    def test_rejects_ambiguous_header(self):
        with self.assertRaises(RequestFileError):
            parse("time,id,passenger_id,source,dest\n0,a,b,1,2\n")

    def test_rejects_bad_input(self):
        header = "time,passenger_id,source,destination\n"
        cases = {
            "missing column": "time,passenger_id,source\n0,a,1\n",
            "non-integer": header + "0.5,a,1,2\n",
            "same floor": header + "0,a,3,3\n",
            "out of range": header + "0,a,1,11\n",
            "floor zero": header + "0,a,0,2\n",
            "negative time": header + "-1,a,1,2\n",
            "duplicate id": header + "0,a,1,2\n1,a,2,3\n",
            "empty id": header + "0,,1,2\n",
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(RequestFileError):
                parse(text)

    def test_rejects_floor_below_one_without_a_floor_count(self):
        with self.assertRaises(RequestFileError):
            read_requests(io.StringIO("time,id,source,dest\n0,a,0,5\n"))

    def test_error_reports_line_number(self):
        with self.assertRaises(RequestFileError) as ctx:
            parse("time,passenger_id,source,destination\n0,a,1,2\n0,b,1,x\n")
        self.assertEqual(ctx.exception.line, 3)


if __name__ == "__main__":
    unittest.main()
