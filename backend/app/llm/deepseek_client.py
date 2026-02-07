from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

from app.core.config import get_settings

settings = get_settings()


class DeepSeekClient:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
        self.model = settings.deepseek_model

    async def chat(self, *, system: str, user: str, temperature: float = 0.1) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or ""
        return content.strip()

    async def chat_stream(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.1,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        stream = await self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )

        chunks: list[str] = []
        async for chunk in stream:
            if not chunk.choices:
                continue
            token = chunk.choices[0].delta.content or ""
            if not token:
                continue
            chunks.append(token)
            if on_token is not None:
                await on_token(token)

        return "".join(chunks).strip()


deepseek_client = DeepSeekClient()
