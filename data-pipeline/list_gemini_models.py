"""List Gemini models visible to the configured API key.

This diagnostic only calls the model-list endpoint. It does not generate
content, upload images, change .env, or modify pipeline output.
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = Path(__file__).resolve().parent
load_dotenv(PIPELINE_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")


def model_value(model, name, default=None):
    value = getattr(model, name, default)
    return default if value is None else value


def main():
    parser = argparse.ArgumentParser(description="List Gemini models available to AUXILIUM's configured API key.")
    parser.add_argument("--all", action="store_true", help="Show all listed models, not only generateContent candidates.")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY was not found in data-pipeline/.env or the environment.")

    from google import genai

    client = genai.Client(api_key=api_key)
    models = list(client.models.list())
    print(f"Models visible to this API key: {len(models)}")
    print("No API key value is displayed.")

    for model in sorted(models, key=lambda item: model_value(item, "name", "")):
        name = model_value(model, "name", "")
        supported_actions = list(model_value(model, "supported_actions", []) or [])
        supported_methods = list(model_value(model, "supported_generation_methods", []) or [])
        actions = supported_actions or supported_methods
        can_generate = "generateContent" in actions or "generate_content" in actions
        # The API model list exposes generation capabilities, while Google's
        # model catalog identifies which Gemini generation models accept image
        # input. Keep this diagnostic conservative: report candidates instead
        # of claiming image support from a name alone.
        is_gemini_generation_model = name.startswith("models/gemini-")
        if not args.all and not (can_generate and is_gemini_generation_model):
            continue
        print(f"ID: {name}")
        print(f"  display_name: {model_value(model, 'display_name', '')}")
        print(f"  supported_actions: {', '.join(actions) or '(not exposed)'}")
        print(f"  generateContent: {'yes' if can_generate else 'no'}")
        print(f"  image-input candidate: {'verify in model catalog' if can_generate and is_gemini_generation_model else 'no'}")
        print(f"  input_token_limit: {model_value(model, 'input_token_limit', '(not exposed)')}")
        print(f"  output_token_limit: {model_value(model, 'output_token_limit', '(not exposed)')}")


if __name__ == "__main__":
    main()
