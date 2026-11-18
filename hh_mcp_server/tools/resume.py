from typing import Any

from fastmcp import FastMCP

from hh_mcp_server.constants import TOOL_TIMEOUT_SECONDS
from hh_mcp_server.drivers.browser import get_page
from hh_mcp_server.scraping.resume import (
    edit_resume as _edit_resume,
    get_my_resumes as _get_resumes,
    parse_resume_page,
)
from hh_mcp_server.utils.auth import ensure_authenticated


def register_resume_tools(mcp: FastMCP) -> None:

    @mcp.tool(timeout=TOOL_TIMEOUT_SECONDS, title="Get My Resumes")
    async def get_my_resumes() -> list[dict[str, Any]]:
        """Get list of user's resumes on hh.ru."""
        page = await get_page()
        await ensure_authenticated(page)
        return await _get_resumes(page)

    @mcp.tool(timeout=TOOL_TIMEOUT_SECONDS, title="Get Resume")
    async def get_resume(resume_id: str) -> dict[str, Any]:
        """Get full resume content.

        Args:
            resume_id: Resume ID (from get_my_resumes)
        """
        page = await get_page()
        await ensure_authenticated(page)
        return await parse_resume_page(page, resume_id)

    @mcp.tool(timeout=TOOL_TIMEOUT_SECONDS, title="Edit Resume")
    async def edit_resume(resume_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Edit and save selected fields of a user's resume on hh.ru.

        Args:
            resume_id: Resume ID (from get_my_resumes)
            updates: Sections to edit. Supports about/about_me (string),
                key_skills (list or comma-separated string), title, salary,
                professional_roles (list or semicolon-separated string), and
                experience (list of objects with id and optional company,
                position, description). Legacy names
                resume_title, desired_position and salary_expectation are
                accepted as aliases.
        """
        page = await get_page()
        await ensure_authenticated(page)
        return await _edit_resume(page, resume_id, updates)
