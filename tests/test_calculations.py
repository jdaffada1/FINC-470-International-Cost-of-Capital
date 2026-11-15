import unittest
from calculations import calculate, verify

class CostOfCapitalTests(unittest.TestCase):
    def test_lecture_and_invariants(self):
        for label, ok in verify().items():
            self.assertTrue(ok, label)

    def test_no_rounding(self):
        x=calculate(.8,.3,.35,.065,.04,.12,.015)
        self.assertAlmostEqual(x.foreign_spread,.015*1.12/1.04,places=12)

if __name__=='__main__':
    unittest.main()
