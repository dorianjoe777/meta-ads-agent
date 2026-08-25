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
        "Lectura verificada del negocio y de sus anuncios. "
        "Esta propuesta conecta oferta, público, mensaje, presupuesto y medición con acciones concretas, "
        "sin inventar resultados ni afirmar que algo ya fue ejecutado. "
        f"Referencia {marker}. "
    )
    return {field: base for field in compiler.PLAN_FIELDS}


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

        def codex(prompt, schema, *, config, timeout, model=None, **kwargs):
            calls.append((model, prompt, schema, timeout, kwargs.get("reasoning_effort")))
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
        self.assertEqual([call[4] for call in calls], ["low", "low"])
        self.assertEqual(result["model"], compiler.TERRA_MODEL)
        self.assertEqual(result["provider"], "openai-codex")
        self.assertEqual(result["reasoning_effort"], "low")
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(
            [attempt["reasoning_effort"] for attempt in result["attempts"]],
            ["low", "low"],
        )
        gemini.assert_not_called()

    def test_invalid_sol_plan_falls_back_to_terra(self):
        calls = []

        def codex(_prompt, _schema, *, config, timeout, model=None, **kwargs):
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
        oversized["advertising_opportunity"] = "análisis publicitario " * 400
        self.assertGreater(len(oversized["advertising_opportunity"]), compiler.MAX_SECTION_CHARS)

        def codex(_prompt, _schema, *, config, timeout, model=None, **kwargs):
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

    def test_rejects_shallow_plan_and_unsupported_schema(self):
        shallow = {field: "texto breve" for field in compiler.PLAN_FIELDS}
        self.assertEqual(compiler._validate_plan(shallow)[1], "strategic_plan_too_shallow")
        unsupported = complete_plan()
        unsupported["organic_strategy"] = "contenido orgánico no permitido"
        self.assertEqual(compiler._validate_plan(unsupported)[1], "strategic_plan_invalid_schema")

    def test_deadline_zero_makes_no_provider_call(self):
        with mock.patch.object(compiler, "_terra_compile") as codex, \
             mock.patch.object(compiler, "_gemini_compile") as gemini:
            result = compiler.compile_strategic_plan({}, {}, config=self.config(), timeout=0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "strategic_plan_timeout")
        codex.assert_not_called()
        gemini.assert_not_called()

    def test_primary_model_receives_main_window_with_fallback_reserves(self):
        with mock.patch.object(compiler.time, "monotonic", return_value=100.0):
            self.assertEqual(compiler._attempt_timeout(340.0, 3), 180)
            self.assertEqual(compiler._attempt_timeout(340.0, 2), 210)
            self.assertEqual(compiler._attempt_timeout(340.0, 1), 240)

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

    def test_schema_has_exactly_five_required_top_level_strings(self):
        schema = compiler.strategic_plan_schema()
        self.assertEqual(tuple(schema["properties"]), compiler.PLAN_FIELDS)
        self.assertEqual(schema["required"], list(compiler.PLAN_FIELDS))
        self.assertFalse(schema["additionalProperties"])
        self.assertTrue(all(item["type"] == "string" for item in schema["properties"].values()))
        self.assertTrue(all(
            item["maxLength"] > compiler.MAX_SECTION_CHARS
            for item in schema["properties"].values()
        ))
        self.assertEqual(
            compiler.PLAN_FIELDS,
            (
                "advertising_opportunity",
                "audience_and_message",
                "campaign_and_creative_plan",
                "budget_and_measurement",
                "next_steps_and_questions",
            ),
        )

    def test_prompt_is_compact_ads_focused_and_discussable(self):
        prompt = compiler._build_prompt(
            {"business": "Rodeo", "price": "$110.000 COP"},
            {"campaigns": [{"status": "PAUSED"}]},
        )
        for field in compiler.PLAN_FIELDS:
            self.assertIn(field, prompt)
        self.assertIn("propuesta inicial de anuncios", prompt.lower())
        self.assertIn("propuesta inicial", prompt.lower())
        self.assertIn("anuncios", prompt.lower())
        self.assertIn("no incluyas referidos", prompt.lower())
        self.assertIn("estrategia orgánica", prompt.lower())

    def test_rejects_a_section_cut_off_mid_sentence(self):
        plan = complete_plan("frase-completa")
        plan["advertising_opportunity"] = (
            "Esta sección tiene suficiente profundidad y explica una oportunidad publicitaria concreta, "
            "pero termina abruptamente sin cerrar la última idea"
        )
        self.assertEqual(
            compiler._validate_plan(plan)[1],
            "strategic_plan_incomplete_sentence",
        )


if __name__ == "__main__":
    unittest.main()
