import unittest

from aura_coder.corpus import ALL_CLASSES, all_variants, stream
from aura_coder.operators import OPERATORS, candidates
from aura_coder.runner import delta, features, msg_pattern, run_tests


class Corpus(unittest.TestCase):
    def test_variants_fail_and_reference_passes(self):
        vs = all_variants()
        self.assertGreaterEqual(len(vs), 30)
        self.assertEqual({v.bug for v in vs}, set(ALL_CLASSES))
        for v in vs:
            self.assertTrue(run_tests(v.fixed, v.tests).ok, v.tid)
            self.assertFalse(run_tests(v.source, v.tests).ok, v.tid)

    def test_stream_is_deterministic_and_shifts(self):
        a, b = stream(3, 60), stream(3, 60)
        self.assertEqual([t.tid for t in a], [t.tid for t in b])
        self.assertEqual({t.phase for t in a[:20]}, {"A"})
        self.assertIn("C", {t.phase for t in a[40:]})


class Operators(unittest.TestCase):
    def test_every_variant_solvable_by_some_operator(self):
        for v in all_variants():
            f = features(v.source, run_tests(v.source, v.tests))
            ok = any(run_tests(c, v.tests).ok for op in OPERATORS for c in candidates(v.source, f, op))
            self.assertTrue(ok, v.tid)


class Features(unittest.TestCase):
    def test_msg_pattern(self):
        self.assertEqual(msg_pattern("name 'math' is not defined"), "name '_' is not defined")
        self.assertEqual(msg_pattern("'NoneType' object has no attribute 'split'"),
                         "'NoneType' object has no attribute '_'")

    def test_delta(self):
        self.assertEqual(delta(9, 10), "off-by-one")
        self.assertEqual(delta(-4, 4), "sign")
        self.assertEqual(delta(True, False), "bool-flip")
        self.assertEqual(delta(None, 3), "none")
        self.assertEqual(delta([1], [1, 2]), "len-off-by-one")


if __name__ == "__main__":
    unittest.main()


class Proposer(unittest.TestCase):
    def test_offline_proposer_is_inert(self):
        import os
        from aura_coder import proposer
        from aura_coder.operators import OPERATORS
        os.environ.pop("AURA_CODER_LLM_URL", None)
        self.assertFalse(proposer.register())
        self.assertNotIn("llm_patch", OPERATORS)
        self.assertEqual(list(proposer.llm_patch("def fn(): pass\n", {})), [])
