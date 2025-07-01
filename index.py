from typing import Annotated
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
import markdownify
from mcp import ErrorData, McpError
from mcp.server.auth.provider import AccessToken
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, TextContent
from openai import BaseModel
from pydantic import AnyUrl, Field
import readabilipy
from pathlib import Path
from pdfminer.high_level import extract_text

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

class Fetch:
    IGNORE_ROBOTS_TXT = True
    USER_AGENT = "Puch/1.0 (Autonomous)"

    @classmethod
    async def fetch_url(cls, url: str, user_agent: str, force_raw: bool = False) -> tuple[str, str]:
        from httpx import AsyncClient, HTTPError

        async with AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    follow_redirects=True,
                    headers={"User-Agent": user_agent},
                    timeout=30,
                )
            except HTTPError as e:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url}: {e!r}"))
            if response.status_code >= 400:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Failed to fetch {url} - status code {response.status_code}"))

            page_raw = response.text

        content_type = response.headers.get("content-type", "")
        is_page_html = ("<html" in page_raw[:100] or "text/html" in content_type or not content_type)

        if is_page_html and not force_raw:
            return cls.extract_content_from_html(page_raw), ""

        return (page_raw, f"Content type {content_type} cannot be simplified to markdown, but here is the raw content:\n")

    @staticmethod
    def extract_content_from_html(html: str) -> str:
        ret = readabilipy.simple_json.simple_json_from_html_string(html, use_readability=True)
        if not ret["content"]:
            return "<error>Page failed to be simplified from HTML</error>"
        content = markdownify.markdownify(ret["content"], heading_style=markdownify.ATX)
        return content

mcp = FastMCP("My MCP Server", auth=SimpleBearerAuthProvider(TOKEN))

ResumeToolDescription = RichToolDescription(
    description="Serve your resume in plain markdown.",
    use_when="Puch (or anyone) asks for your resume; this must return raw markdown, no extra formatting.",
    side_effects=None,
)

RESUME_PATH = Path("./resume.pdf")  # Update to resume.html or resume.txt if needed

@mcp.tool(description=ResumeToolDescription.model_dump_json())
async def resume() -> str:
    if not RESUME_PATH.exists():
        return "<error>Resume file not found.</error>"

    try:
        if RESUME_PATH.suffix == ".pdf":
            text = extract_text(str(RESUME_PATH))
        elif RESUME_PATH.suffix == ".html":
            html = RESUME_PATH.read_text()
            text = markdownify.markdownify(html, heading_style=markdownify.ATX)
        elif RESUME_PATH.suffix == ".txt":
            text = RESUME_PATH.read_text()
        else:
            return f"<error>Unsupported resume file type: {RESUME_PATH.suffix}</error>"

        if not text.strip():
            return "<error>Resume file was empty or unreadable.</error>"

        return text.strip()

    except Exception as e:
        return f"<error>Failed to read resume: {e}</error>"

@mcp.tool
async def validate() -> str:
    return MY_NUMBER

FetchToolDescription = RichToolDescription(
    description="Fetch a URL and return its content.",
    use_when="Use this tool when the user provides a URL and asks for its content, or when the user wants to fetch a webpage.",
    side_effects="The user will receive the content of the requested URL in a simplified format, or raw HTML if requested.",
)

@mcp.tool(description=FetchToolDescription.model_dump_json())
async def fetch(
    url: Annotated[AnyUrl, Field(description="URL to fetch")],
    max_length: Annotated[int, Field(default=5000, description="Maximum number of characters to return.", gt=0, lt=1000000)] = 5000,
    start_index: Annotated[int, Field(default=0, description="Start reading from this index.", ge=0)] = 0,
    raw: Annotated[bool, Field(default=False, description="Get raw HTML if True")] = False,
) -> list[TextContent]:
    url_str = str(url).strip()
    if not url:
        raise McpError(ErrorData(code=INVALID_PARAMS, message="URL is required"))

    content, prefix = await Fetch.fetch_url(url_str, Fetch.USER_AGENT, force_raw=raw)
    original_length = len(content)
    if start_index >= original_length:
        content = "<error>No more content available.</error>"
    else:
        truncated_content = content[start_index : start_index + max_length]
        if not truncated_content:
            content = "<error>No more content available.</error>"
        else:
            content = truncated_content
            actual_content_length = len(truncated_content)
            remaining_content = original_length - (start_index + actual_content_length)
            if actual_content_length == max_length and remaining_content > 0:
                next_start = start_index + actual_content_length
                content += f"\n\n<error>Content truncated. Call the fetch tool with a start_index of {next_start} to get more content.</error>"
    return [TextContent(type="text", text=f"{prefix}Contents of {url}:\n{content}")]

async def main():
    await mcp.run_async("streamable-http", host="0.0.0.0", port=8085)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

