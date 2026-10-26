import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from elevator_sim import NearestCarScheduler, Passenger, Simulation, SimulationConfig
from elevator_sim.replay import TraceRecorder, build_page, main


class ReplayTest(unittest.TestCase):
    def test_one_frame_per_tick_and_data_embeds(self):
        config = SimulationConfig(num_elevators=2, num_floors=6, capacity=4)
        recorder = TraceRecorder()
        passengers = [Passenger("a", 1, 4, 0), Passenger("b", 5, 2, 1)]
        result = Simulation(config, passengers, NearestCarScheduler(), [recorder]).run()

        self.assertEqual(len(recorder.frames), result.ticks)
        self.assertEqual([f["t"] for f in recorder.frames], list(range(result.ticks)))
        self.assertEqual(recorder.frames[-1]["done"], 2)
        self.assertEqual(recorder.frames[1]["down"], {5: 1})  # b has just asked, on floor 5, going down

        page = build_page("t", {"floors": 6}, recorder.frames, "summary </pre> here")
        data = json.loads(re.search(r"const DATA = (.*);\n", page).group(1).replace("<\\/", "</"))
        self.assertEqual(len(data["frames"]), result.ticks)
        self.assertNotIn("summary </pre>", page)  # summary text is escaped


    def test_timeout_exits_1_but_still_writes_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path, out = os.path.join(tmp, "r.csv"), os.path.join(tmp, "replay.html")
            with open(csv_path, "w") as f:
                f.write("time,id,source,dest\n0,a,1,9\n")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = main([csv_path, "--out", out, "--max-ticks", "3"])
            self.assertEqual(code, 1)
            self.assertIn("not delivered", err.getvalue())
            self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
