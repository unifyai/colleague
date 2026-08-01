import unittest
from datetime import date
from unittest.mock import patch

import weekly_orders_report as report


class WeeklyOrdersReportTest(unittest.TestCase):
    def test_week_before(self):
        self.assertEqual(
            report.week_before(date(2026, 8, 3)),
            (date(2026, 7, 27), date(2026, 8, 2)),
        )

    @patch.object(report, "fetch_orders")
    def test_build_report(self, fetch_orders):
        fetch_orders.side_effect = [
            [
                {
                    "order_id": "1",
                    "date": "2026-07-27",
                    "region": "north",
                    "units": 2,
                    "unit_price_cents": 300,
                },
                {
                    "order_id": "2",
                    "date": "2026-08-02",
                    "region": "south",
                    "units": 3,
                    "unit_price_cents": 200,
                },
                {
                    "order_id": "3",
                    "date": "2026-08-02",
                    "region": "north",
                    "units": 1,
                    "unit_price_cents": 200,
                },
            ],
            [{"units": 4, "unit_price_cents": 250}],
        ]

        result = report.build_report(date(2026, 8, 3))

        self.assertEqual(
            result,
            {
                "week_start": "2026-07-27",
                "week_end": "2026-08-02",
                "total_units": 6,
                "total_revenue_cents": 1400,
                "revenue_by_region_cents": {"north": 800, "south": 600},
                "wow_revenue_change_pct": 40.0,
            },
        )
        self.assertEqual(
            fetch_orders.call_args_list[0].args,
            (date(2026, 7, 27), date(2026, 8, 2)),
        )
        self.assertEqual(
            fetch_orders.call_args_list[1].args,
            (date(2026, 7, 20), date(2026, 7, 26)),
        )


if __name__ == "__main__":
    unittest.main()
