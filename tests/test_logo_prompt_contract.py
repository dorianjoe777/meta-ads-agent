import unittest

from codex_brand_guides import build_codex_image_prompt_package


class PureLogoPromptContractTests(unittest.TestCase):
    def test_logo_purpose_is_not_routed_as_an_ad_or_mockup(self):
        package = build_codex_image_prompt_package(
            request="Crear el logo de Odontóloga María Flores en azul y rosado, con una sonrisa sutil.",
            purpose="logo",
            variations=1,
        )
        prompt = package["prompts"][0]["image_prompt"]
        self.assertIn("logotipo puro y aislado", prompt)
        self.assertIn("Prohibidos mockups", prompt)
        self.assertIn("El único texto permitido", prompt)
        self.assertNotIn("Producto u oferta al centro", prompt)
        self.assertNotIn("llamada a la accion abajo", prompt)
        self.assertIn("exclusivamente el activo del logotipo", package["codex_prompt"])


if __name__ == "__main__":
    unittest.main()
