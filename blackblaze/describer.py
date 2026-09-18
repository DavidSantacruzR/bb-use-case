"""Short AI descriptions of a file's contents: a caption for an image, a
summary for text."""

import base64

import anthropic

CAPTION_PROMPT = (
    "Write a single-sentence caption describing what this image shows. "
    "Be concrete and specific. Do not start with 'This image shows'. "
    "Reply with the caption only."
)

SUMMARY_PROMPT = (
    "Write a one or two sentence summary of what this document is about. "
    "Reply with the summary only."
)


class DescriptionUnavailable(Exception):
    """Raised when no description could be produced for a file."""


class ClaudeDescriber:
    def __init__(self, api_key: str, model: str, max_text_chars: int) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_text_chars = max_text_chars

    @property
    def model(self) -> str:
        return self._model

    def describe(self, data: bytes, media_type: str) -> str:
        if media_type.startswith("image/"):
            content = self._image_content(data, media_type)
        else:
            content = self._text_content(data)

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=150,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIError as error:
            raise DescriptionUnavailable(str(error)) from error

        # Guard the stop reason before touching content: a refusal comes back as
        # a 200 with no usable text, and max_tokens leaves a truncated fragment.
        if response.stop_reason == "refusal":
            raise DescriptionUnavailable("the model declined to describe this file")

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        if not text:
            raise DescriptionUnavailable("the model returned no description")
        return text

    def _image_content(self, data: bytes, media_type: str) -> list[dict]:
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            },
            {"type": "text", "text": CAPTION_PROMPT},
        ]

    def _text_content(self, data: bytes) -> list[dict]:
        body = data.decode("utf-8", errors="replace")[: self._max_text_chars]
        return [{"type": "text", "text": f"{SUMMARY_PROMPT}\n\n<document>\n{body}\n</document>"}]
