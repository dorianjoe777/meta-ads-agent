import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import strategic_plan_compiler as compiler


def complete_plan(marker="detalle"):
    base = (
        "Hecho verificado y análisis específico del negocio. "
        "Esta sección conecta precios, costos totales, margen, capacidad, demanda, oferta y decisiones "
        "con acciones medibles, dependencias claras y criterios concretos para avanzar sin inventar resultados. "
        f"Referencia {marker}. "
    )
    plan = {field: (base * 3) for field in compiler.PLAN_FIELDS}
    plan["roadmap"] = (
        "Corto plazo (0-90 días): validar oferta, medición y capacidad con entregables y una puerta de decisión. "
        "Mediano plazo (3-6 meses): escalar solo lo validado, reforzar seguimiento, recurrencia y rentabilidad. "
        "Largo plazo (6-12+ meses): consolidar cartera, marca, automatización operativa y expansión rentable. "
        + base * 2
    )
    return plan


class StrategicPlanCompilerTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(
            codex_cli="codex",
            hermes_home="/tmp/hermes",
            gemini_api_key="gem-secret-key",
            agent_chat_api="",
            agent_chat_base_url="",
            agent_chat_api_key="",
        )

    def test_codex_order_is_sol_then_terra_and_valid_result_stops_chain(self):
        calls = []

        def codex(prompt, schema, *, config, timeout, model=None):
            calls.append((model, prompt, schema, timeout))
            if model == compiler.SOL_MODEL:
                return {"ok": False, "reason": "rate_limit"}
            return {"ok": True, "compiled": complete_plan(model)}

        with mock.patch.object(compiler, "_codex_auth_available", return_value=True), \
             mock.patch.object(compiler, "_terra_compile", side_effect=codex), \
             mock.patch.object(compiler, "_gemini_compile") as gemini:
            result = compiler.compile_strategic_plan(
                {"business": "Rodeo", "margin": "75%"},
                {"campaigns": [{"status": "PAUSED"}]},
                config=self.config(),
            )

        self.assertTrue(result["ok"])
        self.assertEqual([call[0] for call in calls], [compiler.SOL_MODEL, compiler.TERRA_MODEL])
        self.assertEqual(result["model"], compiler.TERRA_MODEL)
        self.assertEqual(result["provider"], "openai-codex")
        self.assertEqual(len(result["attempts"]), 2)
        gemini.assert_not_called()

    def test_invalid_sol_plan_falls_back_to_terra(self):
        calls = []

        def codex(_prompt, _schema, *, config, timeout, model=None):
            calls.append(model)
            if model == compiler.SOL_MODEL:
                return {"ok": True, "compiled": {"diagnosis": "demasiado corto"}}
            return {"ok": True, "compiled": complete_plan()}

        with mock.patch.object(compiler, "_codex_auth_available", return_value=True), \
             mock.patch.object(compiler, "_terra_compile", side_effect=codex):
            result = compiler.compile_strategic_plan({}, {}, config=self.config())

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [compiler.SOL_MODEL, compiler.TERRA_MODEL])
        self.assertEqual(result["attempts"][0]["reason"], "strategic_plan_invalid_schema")

    def test_oversized_sol_section_falls_back_to_terra(self):
        calls = []
        oversized = complete_plan("oversized")
        oversized["diagnosis"] = "análisis estratégico " * 400
        self.assertGreater(len(oversized["diagnosis"]), compiler.MAX_SECTION_CHARS)

        def codex(_prompt, _schema, *, config, timeout, model=None):
            calls.append(model)
            if model == compiler.SOL_MODEL:
                return {"ok": True, "compiled": oversized}
            return {"ok": True, "compiled": complete_plan("terra")}

        with mock.patch.object(compiler, "_codex_auth_available", return_value=True), \
             mock.patch.object(compiler, "_terra_compile", side_effect=codex):
            result = compiler.compile_strategic_plan({}, {}, config=self.config())

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [compiler.SOL_MODEL, compiler.TERRA_MODEL])
        self.assertEqual(
            result["attempts"][0]["reason"],
            "strategic_plan_section_too_large",
        )

    def test_without_codex_auth_starts_with_gemini_37(self):
        seen = {}

        def gemini(model, prompt, schema, **kwargs):
            seen.update(model=model, prompt=prompt, schema=schema, kwargs=kwargs)
            return {"ok": True, "compiled": complete_plan(model)}

        with mock.patch.object(compiler, "_codex_auth_available", return_value=False), \
             mock.patch.object(compiler, "_terra_compile") as codex, \
             mock.patch.object(compiler, "_gemini_compile", side_effect=gemini):
            result = compiler.compile_strategic_plan(
                {"name": "Rodeo", "costs": "25%"},
                {"active": [], "paused": ["Campaña A"], "historical": ["Campaña B"]},
                config=self.config(),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(seen["model"], compiler.GEMINI_MODEL)
        self.assertIn("Rodeo", seen["prompt"])
        self.assertIn("Campaña A", seen["prompt"])
        self.assertIn("Campaña B", seen["prompt"])
        self.assertEqual(set(seen["schema"]["properties"]), set(compiler.PLAN_FIELDS))
        codex.assert_not_called()

    def test_failed_codex_models_fall_back_to_gemini(self):
        with mock.patch.object(compiler, "_codex_auth_available", return_value=True), \
             mock.patch.object(
                 compiler,
                 "_terra_compile",
                 return_value={"ok": False, "reason": "provider_unavailable"},
             ) as codex, \
             mock.patch.object(
                 compiler,
                 "_gemini_compile",
                 return_value={"ok": True, "compiled": complete_plan("gemini")},
             ) as gemini:
            result = compiler.compile_strategic_plan({}, {}, config=self.config())

        self.assertTrue(result["ok"])
        self.assertEqual(codex.call_count, 2)
        gemini.assert_called_once()
        self.assertEqual(result["model"], compiler.GEMINI_MODEL)

    def test_rejects_shallow_plan_and_missing_roadmap_horizons(self):
        shallow = {field: "texto breve" for field in compiler.PLAN_FIELDS}
        deep_without_horizons = complete_plan()
        deep_without_horizons["roadmap"] = (
            "Una secuencia profunda de acciones, responsables, dependencias, entregables, métricas y puertas de "
            "decisión para organizar el crecimiento del negocio sin inventar resultados observados. " * 4
        )

        self.assertEqual(compiler._validate_plan(shallow)[1], "strategic_plan_too_shallow")
        self.assertEqual(
            compiler._validate_plan(deep_without_horizons)[1],
            "strategic_plan_missing_horizons",
        )

    def test_deadline_zero_makes_no_provider_call(self):
        with mock.patch.object(compiler, "_terra_compile") as codex, \
             mock.patch.object(compiler, "_gemini_compile") as gemini:
            result = compiler.compile_strategic_plan({}, {}, config=self.config(), timeout=0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "strategic_plan_timeout")
        codex.assert_not_called()
        gemini.assert_not_called()

    def test_result_returned_after_deadline_is_discarded(self):
        def slow_codex(*_args, **_kwargs):
            time.sleep(0.02)
            return {"ok": True, "compiled": complete_plan()}

        no_gemini = self.config()
        no_gemini.gemini_api_key = ""
        with mock.patch.object(compiler, "_codex_auth_available", return_value=True), \
             mock.patch.object(compiler, "_terra_compile", side_effect=slow_codex) as codex:
            result = compiler.compile_strategic_plan(
                {}, {}, config=no_gemini, timeout=0.005,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "strategic_plan_timeout")
        self.assertEqual(codex.call_count, 1)

    def test_prompt_and_return_value_never_leak_secrets(self):
        captured = {}
        secret = "dop_v1_super_secret_value_123456"

        def codex(prompt, _schema, **_kwargs):
            captured["prompt"] = prompt
            return {
                "ok": False,
                "reason": f"provider exploded with {secret}",
                "diagnostic": f"Authorization: Bearer {secret}",
            }

        no_gemini = self.config()
        no_gemini.gemini_api_key = ""
        with mock.patch.object(compiler, "_codex_auth_available", return_value=True), \
             mock.patch.object(compiler, "_terra_compile", side_effect=codex):
            result = compiler.compile_strategic_plan(
                {
                    "name": "Rodeo",
                    "api_key": secret,
                    "notes": f"Authorization: Bearer {secret}",
                },
                {"access_token": secret},
                config=no_gemini,
            )

        self.assertNotIn(secret, captured["prompt"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result["reason"], "strategic_plan_provider_failed")

    def test_schema_has_exactly_twelve_required_top_level_strings(self):
        schema = compiler.strategic_plan_schema()
        self.assertEqual(tuple(schema["properties"]), compiler.PLAN_FIELDS)
        self.assertEqual(schema["required"], list(compiler.PLAN_FIELDS))
        self.assertFalse(schema["additionalProperties"])
        self.assertTrue(all(item["type"] == "string" for item in schema["properties"].values()))
        self.assertTrue(
            all(
                item["maxLength"] == compiler.MAX_SECTION_CHARS
                for item in schema["properties"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
