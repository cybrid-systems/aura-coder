"""Control plane on a real Aura binary (skipped unless AURA_BIN is set)."""
import os
import unittest

from aura_coder.agent import Agent
from aura_coder.corpus import stream

HAVE = bool(os.environ.get("AURA_BIN"))
OBO = {"etype": "AssertionError", "msgpat": "-", "delta": "off-by-one", "node": "-"}
NAME = {"etype": "NameError", "msgpat": "name '_' is not defined", "delta": "-", "node": "Return"}
CAT = {"etype": "TypeError", "msgpat": 'can only concatenate str (not "int") to str', "delta": "-", "node": "Return"}


@unittest.skipUnless(HAVE, "AURA_BIN not set")
class Control(unittest.TestCase):
    def setUp(self):
        from aura_coder.control import AuraControl
        self.c = AuraControl(learn=True)

    def tearDown(self):
        self.c.close()

    def test_seed_decisions(self):
        d = self.c.decide(OBO)
        self.assertEqual(d["cls"], "off-by-one")
        self.assertEqual(d["order"][0], "range_bound_inc")
        self.assertEqual(len(d["order"]), 12)
        self.assertEqual(self.c.decide(NAME)["cls"], "unknown")

    def test_specialize_then_rollback_restores_source(self):
        src0 = self.c.source()
        self.assertFalse(self.c.report(NAME, True, "add_import")["propose"])
        p = self.c.report(NAME, True, "add_import")["propose"]
        self.assertEqual(p["kind"], "specialize")
        self.assertTrue(p["rebind_ok"] and p["eval_ok"])
        self.assertEqual(self.c.decide(NAME)["order"][0], "add_import")
        self.assertNotEqual(self.c.source(), src0)
        self.c.verdict(False)
        self.assertEqual(self.c.source(), src0)
        self.assertEqual(self.c.decide(NAME)["cls"], "unknown")
        # the dropped specialization is blacklisted until its evidence doubles (a class-level promote may follow)
        p2 = self.c.report(NAME, True, "add_import")["propose"]
        self.assertTrue(not p2 or p2["kind"] != "specialize")

    def test_keep_commits_version(self):
        self.c.report(NAME, True, "add_import")
        self.c.report(NAME, True, "add_import")
        self.assertEqual(self.c.verdict(True)["version"], 1)
        self.assertEqual(self.c.decide(NAME)["version"], 1)

    def test_quoted_message_key(self):
        """msgpat with double quotes must round-trip through the generated classify clause."""
        self.c.report(CAT, True, "cast_str")
        p = self.c.report(CAT, True, "cast_str")["propose"]
        self.assertTrue(p and p["rebind_ok"] and p["eval_ok"])
        self.assertEqual(self.c.decide(CAT)["order"][0], "cast_str")


@unittest.skipUnless(HAVE, "AURA_BIN not set")
class AgentSmoke(unittest.TestCase):
    def test_short_adaptive_stream(self):
        a = Agent("adaptive")
        for t in stream(0, 12):
            a.run_task(t)
        a.close()
        self.assertGreaterEqual(sum(e.solved for e in a.episodes), 9)


if __name__ == "__main__":
    unittest.main()
