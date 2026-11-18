import logging
from typing import Any

from playwright.async_api import Page

from hh_mcp_server.constants import BASE_URL
from hh_mcp_server.scraping import selectors as S
from hh_mcp_server.scraping.extractor import extract_resume_id, navigate_and_wait

logger = logging.getLogger(__name__)


async def get_my_resumes(page: Page) -> list[dict]:
    url = f"{BASE_URL}/applicant/resumes"
    await navigate_and_wait(page, url, S.RESUME_CARD)

    cards = await page.query_selector_all(S.RESUME_CARD)
    resumes = []

    for card in cards:
        title_el = await card.query_selector(S.RESUME_TITLE_LINK)
        if not title_el:
            continue

        title = (await title_el.inner_text()).strip()
        href = await title_el.get_attribute("href") or ""
        resume_id = extract_resume_id(href)

        resumes.append({
            "id": resume_id,
            "title": title,
            "url": f"{BASE_URL}/resume/{resume_id}" if resume_id else href,
        })

    return resumes


async def parse_resume_page(page: Page, resume_id: str) -> dict:
    url = f"{BASE_URL}/resume/{resume_id}"
    await navigate_and_wait(page, url)

    await page.wait_for_timeout(2000)
    text = await page.inner_text("body")

    return {
        "id": resume_id,
        "url": url,
        "raw_text": text,
    }


async def edit_resume(page: Page, resume_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Edit sections using the partial-edit routes and controls used by hh.ru."""
    # Keep the names used by the first version of the tool as aliases. This is
    # also convenient for callers that describe fields in natural language.
    aliases = {
        "about_me": "about",
        "resume_title": "title",
        "desired_position": "professional_roles",
        "salary_expectation": "salary",
        "positions": "professional_roles",
    }
    normalized: dict[str, Any] = {}
    for field, value in updates.items():
        normalized[aliases.get(field, field)] = value

    if isinstance(normalized.get("key_skills"), str):
        normalized["key_skills"] = [
            skill.strip() for skill in normalized["key_skills"].split(",") if skill.strip()
        ]

    supported = {"about", "key_skills", "experience", "title", "salary", "professional_roles"}
    unknown = set(normalized) - supported
    if unknown:
        raise ValueError(f"Unsupported resume sections: {', '.join(sorted(unknown))}")
    if not normalized:
        raise ValueError("updates must contain at least one section")

    if "about" in normalized and not isinstance(normalized["about"], str):
        raise ValueError("about must be a string")
    for field_name in ("title", "salary"):
        if field_name in normalized and not isinstance(normalized[field_name], str):
            raise ValueError(f"{field_name} must be a string")
    if "professional_roles" in normalized:
        roles = normalized["professional_roles"]
        if isinstance(roles, str):
            normalized["professional_roles"] = [
                role.strip() for role in roles.split(";") if role.strip()
            ]
        if not isinstance(normalized["professional_roles"], list) or not all(
            isinstance(role, str) and role.strip()
            for role in normalized["professional_roles"]
        ):
            raise ValueError("professional_roles must be a list of non-empty strings")
    if "key_skills" in normalized and (
        not isinstance(normalized["key_skills"], list)
        or not all(isinstance(skill, str) for skill in normalized["key_skills"])
    ):
        raise ValueError("key_skills must be a list of strings")
    if "experience" in normalized:
        experiences = normalized["experience"]
        if not isinstance(experiences, list) or not experiences:
            raise ValueError("experience must be a non-empty list of experience updates")
        allowed = {"id", "company", "position", "description"}
        for experience in experiences:
            if not isinstance(experience, dict) or not experience.get("id"):
                raise ValueError("Each experience update must include its hh.ru experience id")
            extra = set(experience) - allowed
            if extra:
                raise ValueError(f"Unsupported experience fields: {', '.join(sorted(extra))}")
            for field_name in ("company", "position", "description"):
                if field_name in experience and not isinstance(experience[field_name], str):
                    raise ValueError(f"experience.{field_name} must be a string")

    saved: list[str] = []

    if "about" in normalized:
        about = normalized["about"]
        await navigate_and_wait(page, f"{BASE_URL}/resume/edit/{resume_id}/about")
        field = page.locator("textarea[data-qa='resume-editor-about']")
        await field.wait_for()
        await field.fill(about)
        await page.locator("button[data-qa='resume-partial-edit-save']").click()
        await page.wait_for_load_state("domcontentloaded")
        saved.append("about")

    if "key_skills" in normalized:
        skills = normalized["key_skills"]
        await navigate_and_wait(page, f"{BASE_URL}/resume/edit/{resume_id}/keySkills")
        input_field = page.locator("input[data-qa='chips-trigger-input']")
        await input_field.wait_for()
        # Existing chips are removed first so key_skills represents the full list.
        deletes = page.locator("button[data-qa='chip-delete-action']")
        for _ in range(await deletes.count()):
            await deletes.first.click()
        for skill in skills:
            await input_field.fill(skill)
            await input_field.press("Enter")
        await page.locator("button[data-qa='resume-partial-edit-save']").click()
        await page.wait_for_load_state("domcontentloaded")
        saved.append("key_skills")

    if "experience" in normalized:
        experiences = normalized["experience"]
        for index, experience in enumerate(experiences):
            experience_id = str(experience["id"])
            await navigate_and_wait(
                page,
                f"{BASE_URL}/profile/edit/experience/{experience_id}?resumeFrom={resume_id}",
            )
            selectors = {
                "company": "input[data-qa*='resume-profile-experience-specific-company-input']",
                "position": "input[data-qa*='resume-profile-experience-specific-position-input']",
                "description": "textarea[data-qa='resume-editor-experience-description-input']",
            }
            for field_name, selector in selectors.items():
                if field_name in experience:
                    await page.locator(selector).first.fill(experience[field_name])
            await page.locator("button[data-qa='profile-layout-save-button']").click()
            await page.wait_for_load_state("domcontentloaded")
            saved.append(f"experience[{index}]")

    position_fields = {"title", "position", "salary", "professional_roles"}
    if position_fields.intersection(normalized):
        await navigate_and_wait(page, f"{BASE_URL}/resume/edit/{resume_id}/position")
        title_input = page.locator("input[data-qa='resume-edit-title-suggest']")
        if "title" in normalized:
            await title_input.wait_for()
            await title_input.fill(normalized["title"])
            await title_input.press("Enter")

        if "salary" in normalized:
            salary_input = page.locator("input[data-qa='resume-salary-amount']")
            await salary_input.wait_for()
            salary_value = normalized["salary"].replace(" ", "").replace("₽", "").replace("руб.", "")
            await salary_input.fill(salary_value)
            await page.locator("input[data-qa='resume-currency-input-RUR']").check()

        if "professional_roles" in normalized:
            add_role = page.locator("[data-qa='resume-position-professional-role-add-button']")
            for role in normalized["professional_roles"]:
                await add_role.click()
                dialog = page.get_by_role("dialog")
                search_input = dialog.locator("input").first
                await search_input.wait_for()
                await search_input.fill(role)
                option = dialog.get_by_text(role, exact=True).first
                await option.wait_for()
                await option.click()

        save = page.locator("button[data-qa='resume-partial-edit-save']")
        await save.wait_for()
        await save.click()
        await page.wait_for_load_state("domcontentloaded")
        saved.extend(sorted(position_fields.intersection(normalized)))

    return {"status": "success", "id": resume_id, "saved_sections": saved, "url": page.url}
