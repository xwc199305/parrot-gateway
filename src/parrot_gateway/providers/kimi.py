from parrot_gateway.providers.openai import OpenAIAdaptor


class KimiAdaptor(OpenAIAdaptor):
    """Kimi/Moonshot adaptor using its OpenAI-compatible endpoint."""

    name = "kimi"
