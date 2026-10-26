"""Regression checks for the desktop panel's high-priority UI contracts.

These checks parse the .pyw source without creating a Tk window, so they can run
in headless CI. The workflow separately compiles all Python sources and runs
the engine's behavioral unit tests.
"""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "tek_motor_paneli.pyw"
PANEL_SOURCE = PANEL_PATH.read_text(encoding="utf-8")
PANEL_TREE = ast.parse(PANEL_SOURCE, filename=str(PANEL_PATH))


def _method(name):
    panel_class = next(
        node for node in PANEL_TREE.body
        if isinstance(node, ast.ClassDef) and node.name == "ControlPanel"
    )
    return next(
        node for node in panel_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


class PanelUIContractTests(unittest.TestCase):
    def test_candidate_table_keeps_both_usdt_prices_and_decision_columns(self):
        method = _method("_build_ui")
        columns = next(
            node.value for node in ast.walk(method)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "columns" for target in node.targets)
        )
        self.assertIsInstance(columns, ast.Tuple)
        values = tuple(ast.literal_eval(item) for item in columns.elts)
        self.assertEqual(
            values,
            ("star", "symbol", "price", "btcturk_price", "score", "timeframe", "phase", "freshness", "decision"),
        )
        self.assertFalse(any("diff" in value.lower() for value in values))

    def test_stale_candidate_cannot_get_strong_opportunity_style(self):
        method = _method("_render_state")
        strong_assignment = next(
            node for node in ast.walk(method)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "strong" for target in node.targets)
        )
        expression = ast.unparse(strong_assignment.value)
        self.assertIn("CANLI AKIŞ GÜNCEL", expression)

    def test_opportunity_and_stop_alert_patterns_are_distinct(self):
        method = _method("_write_alarm_wave")
        source = ast.unparse(method)
        self.assertIn('for _ in range(3)', source)
        self.assertIn('for _ in range(4)', source)
        self.assertIn('880.0', source)
        self.assertIn('1175.0', source)
        self.assertIn('1568.0', source)

    def test_stop_loss_crossing_selects_distinct_stop_alert(self):
        source = ast.unparse(_method("_check_level_watch"))
        self.assertIn("stop_triggered", source)
        self.assertIn("_play_alert", source)
        self.assertIn("stop", source)
        self.assertIn("opportunity", source)

    def test_selected_coin_details_include_conditional_trade_levels(self):
        source = ast.unparse(_method("_selection_changed"))
        for field in ("entry_zone_low", "entry_zone_high", "breakout_level", "stop_loss", "targets"):
            self.assertIn(field, source)
        self.assertIn("targets[:3]", source)

    def test_engine_exit_disables_level_tracking(self):
        source = ast.unparse(_method("_poll"))
        self.assertIn("Seviye Takibi: Kapalı", source)
        self.assertIn("motor durdu", source)

    def test_distribution_packaging_requires_explicit_marker(self):
        workflow_path = ROOT / ".github" / "workflows" / "validate-and-package.yml"
        workflow = workflow_path.read_text(encoding="utf-8")
        condition = "if: github.event_name == 'workflow_dispatch' || contains(github.event.head_commit.message, '[package]')"
        for step in (
            "Her main gönderiminde Sürüm 00 ZIP ve SHA-256 oluştur",
            "Kalıcı GitHub Release indirme dosyalarını otomatik güncelle",
            "GitHub Actions artifact'i de yayımla",
        ):
            step_line = f"- name: {step}"
            self.assertIn(step_line, workflow)
            after_step = workflow.split(step_line, 1)[1].split("\\n", 3)
            self.assertTrue(any(condition in line for line in after_step[:2]), step)


if __name__ == "__main__":
    unittest.main()
