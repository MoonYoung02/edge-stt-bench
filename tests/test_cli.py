import unittest

from sttbench.cli import build_parser


class CliTest(unittest.TestCase):
    def test_evaluate_arguments(self):
        args = build_parser().parse_args(
            [
                "evaluate",
                "--dataset",
                "kcsc",
                "--model",
                "base",
                "--device",
                "cpu",
                "--limit",
                "3",
            ]
        )
        self.assertEqual(args.command, "evaluate")
        self.assertEqual(args.dataset, "kcsc")
        self.assertEqual(args.model, "base")
        self.assertEqual(args.device, "cpu")
        self.assertEqual(args.limit, 3)

    def test_evaluate_all_defaults_to_cpu_only(self):
        args = build_parser().parse_args(["evaluate-all", "--limit", "1"])
        self.assertEqual(args.command, "evaluate-all")
        self.assertEqual(tuple(args.devices), ("cpu",))
        self.assertIsNone(args.models)
        self.assertEqual(args.limit, 1)


if __name__ == "__main__":
    unittest.main()
