import json
import tempfile
import unittest
from pathlib import Path

from sentinelwatch.workflow import make_label_manifest, read_geojson, screen_detections
from sentinelwatch.sma import build_river_aggregate_candidates


ROOT = Path(__file__).parents[1]


class WorkflowTests(unittest.TestCase):
    def test_example_detections_are_screened(self):
        alerts = screen_detections(
            read_geojson(ROOT / "examples/detections.geojson"),
            read_geojson(ROOT / "examples/permits.geojson"),
            "2026-06-01",
        )
        self.assertEqual(2, len(alerts["features"]))
        states = {item["properties"]["id"]: item["properties"]["alert_type"] for item in alerts["features"]}
        self.assertEqual("possible_unpermitted_extraction", states["colab-001"])
        self.assertEqual("permitted_activity_candidate", states["colab-002"])

    def test_label_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "labels.csv"
            count = make_label_manifest(read_geojson(ROOT / "examples/cases.geojson"), output)
            self.assertEqual(2, count)
            self.assertIn("confirmed_extraction", output.read_text(encoding="utf-8"))

    def test_sma_compiler_filters_river_aggregate_sites(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            units = folder / "units.csv"
            sanctions = folder / "sanctions.csv"
            units.write_text(
                "UnidadFiscalizableId;Nombre;Latitud;Longitud;FechaActualizacion;LinkSNIFA\n"
                "1;EXTRACCION DE ARIDOS RIO DEMO;-33.4;-70.6;20-05-26;https://example.org/1\n"
                "2;PLANTA DE ARIDOS SECA;-33.5;-70.7;20-05-26;https://example.org/2\n",
                encoding="utf-8",
            )
            sanctions.write_text(
                "ProcesoSancionId;UnidadFiscalizableId;ProcesoSancionEstado\n55;1;Terminado - Sancion\n",
                encoding="utf-8",
            )
            dataset, review = build_river_aggregate_candidates(units, sanctions)
            self.assertEqual(1, len(dataset["features"]))
            self.assertEqual(1, dataset["features"][0]["properties"]["related_sanction_count"])
            self.assertEqual(1, len(review))


if __name__ == "__main__":
    unittest.main()
