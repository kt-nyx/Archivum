"""Grounded LLM selection/classification workers for draft page assembly."""

from __future__ import annotations

import os
from typing import Any

from pipeline.ai.config import load_ai_settings
from pipeline.common.text_normalize import clean_wiki_snippet
from pipeline.discovery.entity_typing import normalize_title
from pipeline.discovery.instance_bosses import BossCandidate, deterministic_pool_order
from pipeline.generate.draft.llm import llm_json_with_retry
from pipeline.generate.draft.prose_synthesis import _format_evidence_block

_CHARACTER_ROLE_VALUES = ("enemy", "ally", "neutral", "uncertain")


def classify_key_character_role_llm(
    items: list[dict[str, Any]],
    *,
    character_name: str,
    instance_name: str,
    fallback_role: str = "uncertain",
) -> str:
    """LLM tiebreaker for an ambiguous character role, constrained to the enum.

    Only meant to be called when deterministic classification returned
    ``"uncertain"``. Offline / no-LLM / empty-evidence returns ``fallback_role`` so
    the deterministic result (usually ``"uncertain"``) stands.
    """
    if not items:
        return fallback_role
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return fallback_role
    result = llm_json_with_retry(
        required_keys=("role",),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["role"],
            "properties": {"role": {"type": "string", "enum": list(_CHARACTER_ROLE_VALUES)}},
        },
        system_prompt=(
            f"Classify the role of '{character_name}' within the instance '{instance_name}' "
            "using ONLY the evidence. Choose exactly one: 'enemy' (opposes or is fought by "
            "adventurers), 'ally' (aids or fights alongside adventurers), 'neutral' (a non-hostile "
            "figure such as a vendor or bystander), or 'uncertain' if the evidence does not say."
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_key_character_role",
        substep="wiki_first_key_character_role",
    )
    role = str(result.get("role", "")).strip().lower()
    return role if role in _CHARACTER_ROLE_VALUES else fallback_role


_LORE_RELEVANCE_VALUES = ("relevant", "unrelated")


def classify_lore_relevance_llm(
    items: list[dict[str, Any]],
    *,
    page_title: str,
    instance_name: str,
    fallback: str = "unrelated",
) -> str:
    """Decide whether a related cross-page lore source is about this instance.

    Used only for the sparse-instance rescue path, where parent/related prose does
    not literally name the instance. Returns ``"relevant"`` or ``"unrelated"``.
    Offline / no-LLM / empty-evidence returns ``fallback`` (default ``"unrelated"``)
    so related pages are not fused unless explicitly affirmed (overreach control).
    """
    if not items:
        return fallback
    settings = load_ai_settings()
    if not settings.openai_ready or os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return fallback
    result = llm_json_with_retry(
        required_keys=("relevance",),
        response_json_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["relevance"],
            "properties": {"relevance": {"type": "string", "enum": list(_LORE_RELEVANCE_VALUES)}},
        },
        system_prompt=(
            f"You are deciding whether the wiki page '{page_title}' provides lore that is "
            f"directly about the instance '{instance_name}' (its story, history, or denizens), "
            "as opposed to broadly related lore that is not specifically about this instance. "
            "Using ONLY the evidence, answer 'relevant' if the evidence describes this specific "
            "instance, otherwise 'unrelated'."
        ),
        user_prompt=f"Evidence:\n{_format_evidence_block(items)}",
        response_schema_name="wiki_first_lore_relevance",
        substep="wiki_first_lore_relevance",
    )
    relevance = str(result.get("relevance", "")).strip().lower()
    return relevance if relevance in _LORE_RELEVANCE_VALUES else fallback


_POOL_SELECTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["selected"],
    "properties": {
        "selected": {"type": "array", "items": {"type": "string"}},
    },
}

_POOL_SELECTION_SNIPPET_MAX_CHARS = 200
_POOL_SELECTION_CONTEXT_MAX_CHARS = 800

_FORBIDDEN_PILOT_PROMPT_STRINGS = (
    "Scholomance",
    "Western Plaguelands",
    "western plaguelands",
)


def _wiki_path_for_prompt(wiki_url: str) -> str:
    value = str(wiki_url).strip()
    if "/wiki/" in value:
        path = value[value.index("/wiki/") + len("/wiki/") :].split("#", 1)[0].strip("/")
        return f"/wiki/{path}" if path else value
    return value


def _parse_allowlisted_selection(
    result: dict[str, Any],
    allowed: dict[str, str],
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in result.get("selected", []):
        canonical = allowed.get(normalize_title(str(value).strip()))
        if canonical and canonical not in seen:
            seen.add(canonical)
            selected.append(canonical)
    return selected


def _pool_selection_system_prompt(*, instance_name: str, max_count: int) -> str:
    return (
        "You select key characters for a World of Warcraft instance page.\n\n"
        f"Instance: {instance_name}\n\n"
        "Task:\n"
        "- Choose which candidates are key characters for this instance: notable bosses, "
        "enemy NPCs, and lore figures meaningfully tied to this dungeon or raid.\n"
        "- Use ONLY names from the candidate list in the user message. Never invent or rename "
        "characters.\n"
        "- Exclude factions, organizations, locations, subzones, items, and generic trash mobs.\n"
        "- Order selected names by narrative importance (most important first).\n"
        f"- Return at most {max_count} names.\n\n"
        "Output JSON only, matching the required schema."
    )


def _format_pool_selection_user_prompt(
    candidates: list[BossCandidate],
    context_text: str,
) -> str:
    lines = ["Candidates (choose only from this list):", ""]
    for candidate in candidates:
        section_roles: list[str] = []
        snippets: list[str] = []
        for item in candidate.profile_pool or []:
            role = str(item.get("section_role", "")).strip()
            if role and role not in section_roles:
                section_roles.append(role)
            snippet = clean_wiki_snippet(str(item.get("snippet", "")))
            if snippet and len(snippets) < 3:
                snippets.append(snippet[:_POOL_SELECTION_SNIPPET_MAX_CHARS])
        if not section_roles:
            section_roles = [candidate.source_section_role]
        lines.append(f"- name: {candidate.name}")
        lines.append(f"  wiki: {_wiki_path_for_prompt(candidate.wiki_url)}")
        lines.append(f"  sections: {', '.join(section_roles)}")
        lines.append("  evidence:")
        if snippets:
            for snippet in snippets:
                lines.append(f"    - {snippet}")
        else:
            lines.append("    -")
        lines.append("")
    if context_text.strip():
        lines.append("Instance context:")
        lines.append(clean_wiki_snippet(context_text)[:_POOL_SELECTION_CONTEXT_MAX_CHARS])
    return "\n".join(lines)


def _llm_disabled() -> bool:
    settings = load_ai_settings()
    if not settings.openai_ready:
        return True
    return os.environ.get("WOW_LORE_WIKI_FIRST_NO_LLM", "").lower() in {"1", "true", "yes"}


def select_key_characters_from_pool(
    pool: list[BossCandidate],
    *,
    instance_name: str,
    context_text: str = "",
    max_count: int,
    exclude_names: list[str] | None = None,
) -> list[str]:
    """Grounded pool selector: ordered cast names allowlisted to ``pool`` rows."""
    if max_count <= 0 or not pool:
        return []

    exclude_keys = {normalize_title(name) for name in (exclude_names or [])}
    prompt_pool = [
        candidate for candidate in pool if normalize_title(candidate.name) not in exclude_keys
    ]
    if not prompt_pool:
        return []

    def _offline_order() -> list[str]:
        return deterministic_pool_order(
            prompt_pool,
            narrative_text=context_text,
            exclude_normalized_names=exclude_keys,
        )[:max_count]

    if _llm_disabled():
        return _offline_order()

    allowed = {normalize_title(candidate.name): candidate.name for candidate in prompt_pool}
    result = llm_json_with_retry(
        required_keys=("selected",),
        response_json_schema=_POOL_SELECTION_JSON_SCHEMA,
        system_prompt=_pool_selection_system_prompt(
            instance_name=instance_name,
            max_count=max_count,
        ),
        user_prompt=_format_pool_selection_user_prompt(prompt_pool, context_text),
        response_schema_name="wiki_first_key_character_pool_selection",
        substep="wiki_first_key_character_pool_selection",
    )
    selected = _parse_allowlisted_selection(result, allowed)
    if not selected:
        return _offline_order()
    return selected[:max_count]


def select_key_characters_from_narrative(
    candidates: list[dict[str, Any]],
    *,
    instance_name: str,
    narrative_text: str = "",
    max_count: int = 10,
) -> list[str]:
    """Grounded narrative-fallback selector.

    Given deterministic link candidates already mined from the page (each a dict
    with at least ``name``), return the ordered subset that are genuine key
    characters of the instance. Selection is constrained to the provided names,
    so it can never invent a character without a backing wiki link. Offline / no
    LLM falls back to the deterministic ranking already applied by the miner.
    """
    names = [
        str(row.get("name", "")).strip() for row in candidates if str(row.get("name", "")).strip()
    ]
    if not names:
        return []

    if _llm_disabled():
        return names[:max_count]

    allowed = {normalize_title(name): name for name in names}
    result = llm_json_with_retry(
        required_keys=("selected",),
        response_json_schema=_POOL_SELECTION_JSON_SCHEMA,
        system_prompt=(
            f"Select which of the listed names are key characters of the instance '{instance_name}' "
            "(notable bosses, NPCs, leaders, or lore figures tied to this place). Choose ONLY from the "
            "provided names; never invent names. Order by narrative importance. Exclude factions, "
            f"organizations, locations, and items. Return at most {max_count} names."
        ),
        user_prompt="Candidate names:\n"
        + "\n".join(f"- {name}" for name in names)
        + (f"\n\nContext:\n{clean_wiki_snippet(narrative_text)}" if narrative_text.strip() else ""),
        response_schema_name="wiki_first_narrative_character_selection",
        substep="wiki_first_narrative_character_selection",
    )
    selected = _parse_allowlisted_selection(result, allowed)
    if not selected:
        return names[:max_count]
    return selected[:max_count]
