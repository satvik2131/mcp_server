from typing import Annotated
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp import ErrorData, McpError
from mcp.server.auth.provider import AccessToken
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, TextContent
from openai import BaseModel
from pydantic import AnyUrl, Field
from pathlib import Path

TOKEN = "c0b13aceba2a"
MY_NUMBER = "917509593038"

class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: str | None

class SimpleBearerAuthProvider(BearerAuthProvider):
    def __init__(self, token: str):
        k = RSAKeyPair.generate()
        super().__init__(
            public_key=k.public_key, jwks_uri=None, issuer=None, audience=None
        )
        self.token = token

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token == self.token:
            return AccessToken(
                token=token,
                client_id="unknown",
                scopes=[],
                expires_at=None,
            )
        return None

mcp = FastMCP("My MCP Server", auth=SimpleBearerAuthProvider(TOKEN))

ResumeToolDescription = RichToolDescription(
    description="Serve your resume in plain markdown.",
    use_when="Puch (or anyone) asks for your resume; this must return raw markdown, no extra formatting.",
    side_effects=None,
)

RESUME_PATH = Path("resume.md")  # You can also use resume.txt

@mcp.tool(description=ResumeToolDescription.model_dump_json())
async def resume() -> str:
    if not RESUME_PATH.exists():
        return "<error>Resume file not found at resume.md</error>"

    try:
        text = RESUME_PATH.read_text(encoding="utf-8").strip()
        if not text:
            return "<error>Resume file is empty.</error>"
        return text
    except Exception as e:
        return f"<error>Failed to read resume: {e}</error>"

@mcp.tool
async def validate() -> str:
    return MY_NUMBER

FetchToolDescription = RichToolDescription(
    description="Fetch a URL and return its content.",
    use_when="Use this tool when the user provides a URL and asks for its content, or when the user wants to fetch a webpage.",
    side_effects="The user will receive the content of the requested URL.",
)

class Fetch:
    USER_AGENT = "Puch/1.0 (Autonomous)"

    @classmethod
    async def fetch_url(cls, url: str, user_agent: str) -> str:
        from httpx import AsyncClient, HTTPError
        async with AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    headers={"User-Agent": user_agent},
                    timeout=30,
                    follow_redirects=True,
                )
                if response.status_code >= 400:
                    raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Status {response.status_code}"))
                return response.text
            except HTTPError as e:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=str(e)))

@mcp.tool(description=FetchToolDescription.model_dump_json())
async def fetch(
    url: Annotated[AnyUrl, Field(description="URL to fetch")],
    max_length: Annotated[int, Field(default=5000, gt=0, lt=1000000)] = 5000,
    start_index: Annotated[int, Field(default=0, ge=0)] = 0,
) -> list[TextContent]:
    url_str = str(url).strip()
    if not url:
        raise McpError(ErrorData(code=INVALID_PARAMS, message="URL is required"))

    content = await Fetch.fetch_url(url_str, Fetch.USER_AGENT)
    original_length = len(content)

    if start_index >= original_length:
        content = "<error>No more content available.</error>"
    else:
        content = content[start_index : start_index + max_length]
        if len(content) == max_length:
            next_index = start_index + max_length
            content += f"\n\n<error>Truncated. Use start_index={next_index} to fetch more.</error>"

    return [TextContent(type="text", text=f"Contents of {url}:\n{content}")]

async def main():
    await mcp.run_async("streamable-http", host="0.0.0.0", port=8085)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

