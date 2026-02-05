from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional
import logging
import json
import uuid

try:
    from ..deps import get_current_user
    from ...schemas.user import User
    from ...schemas.transcript import (
        TranscriptRequest,
        SaveTranscriptRequest,
    )
    from ...schemas.meeting import (
        SaveSummaryRequest,
        RefineNotesRequest,
        GenerateNotesRequest,
    )
    from ...db import DatabaseManager
    from ...core.rbac import RBAC
    from ...services.summarization import SummarizationService
    from ...services.audio.vad import SimpleVAD
    from ...services.audio.groq_client import GroqTranscriptionClient
    from ...services.chat import ChatService
except (ImportError, ValueError):
    from api.deps import get_current_user
    from schemas.user import User
    from schemas.transcript import (
        TranscriptRequest,
        SaveTranscriptRequest,
    )
    from schemas.meeting import (
        SaveSummaryRequest,
        RefineNotesRequest,
        GenerateNotesRequest,
    )
    from db import DatabaseManager
    from core.rbac import RBAC
    from services.summarization import SummarizationService
    from services.audio.vad import SimpleVAD
    from services.audio.groq_client import GroqTranscriptionClient
    from services.chat import ChatService

# Initialize services
db = DatabaseManager()
rbac = RBAC(db)
processor = SummarizationService()

router = APIRouter()
logger = logging.getLogger(__name__)


# --- Meeting Templates with Optimized Prompts ---
def get_template_prompt(template_id: str) -> str:
    """
    Get the structured prompt for a specific meeting template.
    Optimized for token efficiency while maintaining quality.
    """
    templates = {
        "standard_meeting": """Generate professional meeting notes as valid JSON:

{
  "MeetingName": "Descriptive title from content",
  "People": {"title": "Participants", "blocks": [{"content": "Name - Role"}]},
  "SessionSummary": {"title": "Executive Summary", "blocks": [{"content": "2-3 paragraphs: purpose, topics, outcomes"}]},
  "KeyItemsDecisions": {"title": "Key Decisions", "blocks": [{"content": "Decision - Rationale - Owner/Date"}]},
  "ImmediateActionItems": {"title": "Action Items", "blocks": [{"content": "[Person] will [action] by [deadline]"}]},
  "NextSteps": {"title": "Next Steps", "blocks": [{"content": "What's next - Timeline - Owner"}]},
  "CriticalDeadlines": {"title": "Deadlines", "blocks": [{"content": "[Date] - [Deliverable] - Owner"}]},
  "MeetingNotes": {"meeting_name": "Same as MeetingName", "sections": [{"title": "Topic", "blocks": [{"content": "Details"}]}]}
}

Rules: Extract names/dates/commitments. Make action items SMART. Capture discussions AND decisions. Flag blockers/risks. Be concise. Empty blocks [] if missing. Organize by topic.
""",
        "daily_standup": """Generate Daily Standup notes as valid JSON:

{
  "MeetingName": "Daily Standup - [Team] - [Date]",
  "People": {"title": "Team Members", "blocks": [{"content": "Name - Role"}]},
  "SessionSummary": {"title": "Overview", "blocks": [{"content": "Team progress, velocity, blockers"}]},
  "MeetingNotes": {"meeting_name": "Same as MeetingName", "sections": [{"title": "[Person] - Updates", "blocks": [{"content": "✅ Done: [Task]"}, {"content": "🎯 Today: [Task]"}, {"content": "🚧 Blocked: [Issue]"}]}]},
  "KeyItemsDecisions": {"title": "Decisions", "blocks": [{"content": "Decision - Context"}]},
  "ImmediateActionItems": {"title": "Actions", "blocks": [{"content": "[Person] will [action] - By when"}]},
  "CriticalDeadlines": {"title": "Sprint Deadlines", "blocks": [{"content": "[Date] - [Milestone]"}]},
  "NextSteps": {"title": "Next Standup", "blocks": [{"content": "Items to track"}]}
}

Rules: One section per person. Use ✅ done, 🎯 today, 🚧 blocked. Extract task names/IDs. Highlight dependencies/blockers. Flag recurring issues. Keep brief.
""",
        "brainstorming": """Generate Brainstorming notes as valid JSON:

{
  "MeetingName": "Brainstorming - [Topic]",
  "People": {"title": "Participants", "blocks": [{"content": "Name - Expertise"}]},
  "SessionSummary": {"title": "Overview", "blocks": [{"content": "Problem statement"}, {"content": "Approach used"}, {"content": "Ideas count & selection"}]},
  "MeetingNotes": {"meeting_name": "Same as MeetingName", "sections": [{"title": "Ideas - [Theme]", "blocks": [{"content": "💡 [Title]: Description - By [Person] - Pros/cons"}]}, {"title": "Top Ideas", "blocks": [{"content": "⭐ [Title]: Why selected - Next steps"}]}, {"title": "Parked", "blocks": [{"content": "🅿️ [Title]: Reason - Revisit conditions"}]}]},
  "KeyItemsDecisions": {"title": "Decisions", "blocks": [{"content": "Ideas to pursue - Criteria - Timeline"}]},
  "ImmediateActionItems": {"title": "Validation", "blocks": [{"content": "[Person] will [test] [idea] by [date]"}]},
  "CriticalDeadlines": {"title": "Validation Deadlines", "blocks": [{"content": "[Date] - [Milestone] - Owner"}]},
  "NextSteps": {"title": "Follow-up", "blocks": [{"content": "Reconvene when - Prepare what"}]}
}

Rules: Group by theme. Attribute ideas. Note WHY selected/parked. Document constraints. ID quick wins vs long-term. Use 💡 all, ⭐ selected, 🅿️ parked.
""",
        "interview": """Generate Interview Assessment as valid JSON:

{
  "MeetingName": "Interview - [Candidate] - [Position]",
  "People": {"title": "Panel", "blocks": [{"content": "Name - Role - Focus"}]},
  "SessionSummary": {"title": "Candidate Overview", "blocks": [{"content": "Background summary"}, {"content": "Format & areas"}, {"content": "Overall: Hire/No Hire/Maybe"}]},
  "MeetingNotes": {"meeting_name": "Same as MeetingName", "sections": [{"title": "Technical Skills", "blocks": [{"content": "✅ Strength: [Skill] - Evidence"}, {"content": "⚠️ Gap: [Skill] - Example"}]}, {"title": "Behavioral", "blocks": [{"content": "✅ Strength: [Skill] - Examples"}, {"content": "⚠️ Concern: [Area] - Behaviors"}]}, {"title": "Cultural Fit", "blocks": [{"content": "Fit assessment - Examples"}]}, {"title": "Candidate Questions", "blocks": [{"content": "Question - Quality"}]}]},
  "KeyItemsDecisions": {"title": "Assessment", "blocks": [{"content": "Recommendation: [Strong Yes/Yes/Maybe/No/Strong No] - Why"}, {"content": "Salary: [If discussed]"}, {"content": "Notice: [If discussed]"}]},
  "ImmediateActionItems": {"title": "Next Steps", "blocks": [{"content": "[Recruiter] will [action] by [date]"}]},
  "NextSteps": {"title": "Follow-up", "blocks": [{"content": "References - Who"}, {"content": "Additional rounds - Focus"}, {"content": "Comp discussion"}]},
  "CriticalDeadlines": {"title": "Timeline", "blocks": [{"content": "[Date] - Decision deadline"}]}
}

Rules: Use specific examples not impressions. Separate technical/soft skills. Note red flags professionally. Capture candidate questions. Document comp factually. Use ✅ strengths, ⚠️ gaps.
""",
        "project_kickoff": """Generate Project Kickoff notes as valid JSON:

{
  "MeetingName": "Project Kickoff - [Project]",
  "People": {"title": "Team & Stakeholders", "blocks": [{"content": "Name - Role - Responsibilities"}]},
  "SessionSummary": {"title": "Overview", "blocks": [{"content": "Vision & goals"}, {"content": "Success criteria & metrics"}, {"content": "Constraints (budget, timeline, resources)"}]},
  "MeetingNotes": {"meeting_name": "Same as MeetingName", "sections": [{"title": "Scope", "blocks": [{"content": "✅ In: [Item] - Why"}, {"content": "❌ Out: [Item] - Why"}]}, {"title": "RACI", "blocks": [{"content": "[Person] - Responsible for [area] - Accountable to [who]"}]}, {"title": "Timeline", "blocks": [{"content": "[Date/Phase] - [Milestone] - Deliverables"}]}, {"title": "Risks", "blocks": [{"content": "🚨 [Risk] - Impact: H/M/L - Mitigation - Owner"}]}, {"title": "Dependencies", "blocks": [{"content": "Depends on [what] - Impact if delayed"}]}, {"title": "Communication", "blocks": [{"content": "Meeting cadence - Attendees - Purpose"}, {"content": "Status reports - Format - Frequency"}]}]},
  "KeyItemsDecisions": {"title": "Decisions", "blocks": [{"content": "Decision on [what] - Rationale - Alternatives"}]},
  "ImmediateActionItems": {"title": "Immediate Actions", "blocks": [{"content": "[Person] will [action] by [date]"}]},
  "CriticalDeadlines": {"title": "Milestones", "blocks": [{"content": "[Date] - [Milestone] - Owner - Dependencies"}]},
  "NextSteps": {"title": "Follow-up", "blocks": [{"content": "Next meeting: [Date] - Agenda"}, {"content": "Docs to create: [What] - Owner - Due"}]}
}

Rules: Clear in/out scope. Explicit roles. Assess risks early. Document decision rationale. Use ✅ in-scope, ❌ out, 🚨 risks. Flag dependencies.
""",
    }

    return templates.get(template_id, templates["standard_meeting"])


def get_template_structure(template_id: str) -> dict:
    """
    Returns the base structure for each template type.
    This allows for template-specific output structures.
    """
    base_structure = {
        "MeetingName": "",
        "People": {"title": "Participants", "blocks": []},
        "SessionSummary": {"title": "Executive Summary", "blocks": []},
        "KeyItemsDecisions": {"title": "Key Decisions", "blocks": []},
        "ImmediateActionItems": {"title": "Action Items", "blocks": []},
        "NextSteps": {"title": "Next Steps", "blocks": []},
        "CriticalDeadlines": {"title": "Important Deadlines", "blocks": []},
        "MeetingNotes": {"meeting_name": "", "sections": []},
    }

    # Template-specific customizations
    template_structures = {
        "standard_meeting": base_structure,
        "daily_standup": {
            **base_structure,
            "People": {"title": "Team Members Present", "blocks": []},
            "SessionSummary": {"title": "Standup Overview", "blocks": []},
            "CriticalDeadlines": {"title": "Sprint Deadlines", "blocks": []},
        },
        "brainstorming": {
            **base_structure,
            "KeyItemsDecisions": {"title": "Selected Ideas", "blocks": []},
            "ImmediateActionItems": {"title": "Validation Actions", "blocks": []},
        },
        "interview": {
            **base_structure,
            "People": {"title": "Interview Panel", "blocks": []},
            "SessionSummary": {"title": "Candidate Overview", "blocks": []},
            "KeyItemsDecisions": {"title": "Hiring Recommendation", "blocks": []},
        },
        "project_kickoff": {
            **base_structure,
            "People": {"title": "Project Team & Stakeholders", "blocks": []},
            "SessionSummary": {"title": "Project Overview", "blocks": []},
            "CriticalDeadlines": {"title": "Project Milestones", "blocks": []},
        },
    }

    return template_structures.get(template_id, base_structure)


async def process_transcript_background(
    process_id: str,
    transcript: TranscriptRequest,
    custom_prompt: str,
    user_email: Optional[str] = None,
):
    """Background task to process transcript"""
    try:
        logger.info(f"Starting background processing for process_id: {process_id}")

        # Early validation for common issues
        if not transcript.text or not transcript.text.strip():
            raise ValueError("Empty transcript text provided")

        # Default to Gemini if no model specified
        transcript.model = transcript.model or "gemini"
        transcript.model_name = transcript.model_name or "gemini-2.5-flash"

        if transcript.model in ["claude", "groq", "openai", "gemini"]:
            # Check if API key is available in DB or Environment
            api_key = await db.get_api_key(transcript.model, user_email=user_email)
            if not api_key:
                import os

                env_keys = {
                    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
                    "groq": ["GROQ_API_KEY"],
                    "openai": ["OPENAI_API_KEY"],
                    "claude": ["ANTHROPIC_API_KEY"],
                }

                if not any(os.getenv(k) for k in env_keys.get(transcript.model, [])):
                    provider_names = {
                        "claude": "Anthropic",
                        "groq": "Groq",
                        "openai": "OpenAI",
                        "gemini": "Gemini",
                    }
                    raise ValueError(
                        f"{provider_names.get(transcript.model, transcript.model)} API key not configured. Please set your API key in the environmental variables or settings."
                    )

        # Use template-specific prompt if templateId is provided
        template_prompt = custom_prompt
        template_id = getattr(transcript, "templateId", None) or getattr(
            transcript, "template_id", None
        )
        if template_id:
            template_prompt = get_template_prompt(template_id)

        _, all_json_data = await processor.process_transcript(
            text=transcript.text,
            model=transcript.model,
            model_name=transcript.model_name,
            chunk_size=transcript.chunk_size,
            overlap=transcript.overlap,
            custom_prompt=template_prompt,
            user_email=user_email,
        )

        # Get template-specific structure
        final_summary = get_template_structure(template_id or "standard_meeting")

        # Process each chunk's data
        for json_str in all_json_data:
            try:
                logger.info(
                    f"Parsing JSON chunk (len={len(json_str)}): {json_str[:200]}..."
                )
                json_dict = json.loads(json_str)
                logger.info(f"Chunk keys: {list(json_dict.keys())}")

                # Update meeting name
                if "MeetingName" in json_dict and json_dict["MeetingName"]:
                    final_summary["MeetingName"] = json_dict["MeetingName"]

                # Process each section
                for key in final_summary:
                    if key == "MeetingName":
                        continue

                    if key == "MeetingNotes" and key in json_dict:
                        # Handle MeetingNotes sections
                        if isinstance(json_dict[key].get("sections"), list):
                            for section in json_dict[key]["sections"]:
                                if not section.get("blocks"):
                                    section["blocks"] = []
                            final_summary[key]["sections"].extend(
                                json_dict[key]["sections"]
                            )
                        if json_dict[key].get("meeting_name"):
                            final_summary[key]["meeting_name"] = json_dict[key][
                                "meeting_name"
                            ]
                    elif (
                        key in json_dict
                        and isinstance(json_dict[key], dict)
                        and "blocks" in json_dict[key]
                    ):
                        if isinstance(json_dict[key]["blocks"], list):
                            final_summary[key]["blocks"].extend(
                                json_dict[key]["blocks"]
                            )

                            # Also add as a new section in MeetingNotes if not already present
                            section_exists = False
                            for section in final_summary["MeetingNotes"]["sections"]:
                                if section["title"] == json_dict[key]["title"]:
                                    section["blocks"].extend(json_dict[key]["blocks"])
                                    section_exists = True
                                    break

                            if not section_exists:
                                final_summary["MeetingNotes"]["sections"].append(
                                    {
                                        "title": json_dict[key]["title"],
                                        "blocks": json_dict[key]["blocks"].copy()
                                        if json_dict[key]["blocks"]
                                        else [],
                                    }
                                )
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse JSON chunk for {process_id}: {e}. Chunk: {json_str[:100]}..."
                )
            except Exception as e:
                logger.error(
                    f"Error processing chunk data for {process_id}: {e}. Chunk: {json_str[:100]}..."
                )

        # Update database with meeting name using meeting_id
        if final_summary["MeetingName"]:
            await db.update_meeting_name(
                transcript.meeting_id, final_summary["MeetingName"]
            )

        # Save final result
        if all_json_data:
            await db.update_process(
                process_id, status="completed", result=final_summary
            )
            logger.info(f"Background processing completed for process_id: {process_id}")
        else:
            error_msg = "Summary generation failed: No chunks were processed successfully. Check logs for specific errors."
            await db.update_process(process_id, status="failed", error=error_msg)
            logger.error(
                f"Background processing failed for process_id: {process_id} - {error_msg}"
            )

    except ValueError as e:
        # Handle specific value errors (like API key issues)
        error_msg = str(e)
        logger.error(
            f"Configuration error in background processing for {process_id}: {error_msg}",
            exc_info=True,
        )
        try:
            await db.update_process(process_id, status="failed", error=error_msg)
        except Exception as db_e:
            logger.error(
                f"Failed to update DB status to failed for {process_id}: {db_e}",
                exc_info=True,
            )
    except Exception as e:
        # Handle all other exceptions
        error_msg = f"Processing error: {str(e)}"
        logger.error(
            f"Error in background processing for {process_id}: {error_msg}",
            exc_info=True,
        )
        try:
            await db.update_process(process_id, status="failed", error=error_msg)
        except Exception as db_e:
            logger.error(
                f"Failed to update DB status to failed for {process_id}: {db_e}",
                exc_info=True,
            )


async def generate_notes_with_gemini_background(
    meeting_id: str,
    full_transcript_text: str,
    template_id: str,
    meeting_title: str,
    custom_context: str,
    user_email: str,
):
    """
    Background task to generate notes using Gemini.
    """
    template_prompt = get_template_prompt(template_id)
    if custom_context:
        template_prompt += f"\n\nAdditional Context:\n{custom_context}"

    try:
        # 1. Create process
        process_id = await db.create_process(meeting_id)

        # 2. Call processor
        _, all_json_data = await processor.process_transcript(
            text=full_transcript_text,
            model="gemini",
            model_name="gemini-2.5-flash",
            chunk_size=10000,  # larger chunks for notes
            overlap=1000,
            custom_prompt=template_prompt,
            user_email=user_email,
        )

        # 3. Get template-specific structure
        final_result = get_template_structure(template_id)
        final_result["MeetingName"] = meeting_title
        final_result["MeetingNotes"]["meeting_name"] = meeting_title

        # 4. Aggregate results from all chunks
        for json_str in all_json_data:
            try:
                json_dict = json.loads(json_str)

                # Merge logic consistent with process_transcript_background
                for key in final_result:
                    if key == "MeetingName":
                        continue

                    if key == "MeetingNotes" and key in json_dict:
                        if isinstance(json_dict[key].get("sections"), list):
                            for new_section in json_dict[key]["sections"]:
                                # Skip empty sections
                                if not new_section.get("blocks"):
                                    continue

                                # Check if section title already exists
                                existing_section = next(
                                    (
                                        s
                                        for s in final_result[key]["sections"]
                                        if s["title"] == new_section["title"]
                                    ),
                                    None,
                                )

                                if existing_section:
                                    # Merge blocks
                                    existing_section["blocks"].extend(
                                        new_section["blocks"]
                                    )
                                else:
                                    # Append new section
                                    final_result[key]["sections"].append(new_section)

                    elif (
                        key in json_dict
                        and isinstance(json_dict[key], dict)
                        and "blocks" in json_dict[key]
                    ):
                        if (
                            isinstance(json_dict[key]["blocks"], list)
                            and json_dict[key]["blocks"]
                        ):
                            final_result[key]["blocks"].extend(json_dict[key]["blocks"])

                            # Also add to MeetingNotes sections for visibility
                            section_exists = False
                            for section in final_result["MeetingNotes"]["sections"]:
                                if section["title"] == json_dict[key]["title"]:
                                    section["blocks"].extend(json_dict[key]["blocks"])
                                    section_exists = True
                                    break
                            if not section_exists:
                                final_result["MeetingNotes"]["sections"].append(
                                    {
                                        "title": json_dict[key]["title"],
                                        "blocks": json_dict[key]["blocks"],
                                    }
                                )
            except Exception as e:
                logger.error(f"Error merging chunk: {e}")

        # 5. Convert final_result to Markdown
        markdown_output = generate_markdown_from_structure(final_result, template_id)
        final_result["markdown"] = markdown_output

        await db.update_process(process_id, status="completed", result=final_result)

    except Exception as e:
        logger.error(f"Failed to generate notes: {e}")
        # Update process to failed
        try:
            await db.update_process(meeting_id, status="failed", error=str(e))
        except:
            pass


def generate_markdown_from_structure(data: dict, template_id: str) -> str:
    """
    Generate professional markdown notes from the structured data.
    Format varies based on template type.
    """
    markdown = f"# {data.get('MeetingName', 'Meeting Notes')}\n\n"

    # Add metadata
    markdown += "---\n\n"

    # Executive Summary / Overview
    if data.get("SessionSummary", {}).get("blocks"):
        markdown += f"## {data['SessionSummary']['title']}\n\n"
        for block in data["SessionSummary"]["blocks"]:
            markdown += f"{block['content']}\n\n"

    # Participants
    if data.get("People", {}).get("blocks"):
        markdown += f"## {data['People']['title']}\n\n"
        for block in data["People"]["blocks"]:
            markdown += f"- {block['content']}\n"
        markdown += "\n"

    # Template-specific sections
    if template_id == "daily_standup":
        markdown += generate_standup_markdown(data)
    elif template_id == "brainstorming":
        markdown += generate_brainstorming_markdown(data)
    elif template_id == "interview":
        markdown += generate_interview_markdown(data)
    elif template_id == "project_kickoff":
        markdown += generate_project_kickoff_markdown(data)
    else:
        markdown += generate_standard_markdown(data)

    return markdown


def generate_standard_markdown(data: dict) -> str:
    """Generate markdown for standard meetings"""
    md = ""

    # Key Discussion Points
    if data.get("MeetingNotes", {}).get("sections"):
        md += "## Key Discussion Points\n\n"
        for section in data["MeetingNotes"]["sections"]:
            if not section.get("blocks"):
                continue
            md += f"### {section['title']}\n\n"
            for block in section["blocks"]:
                md += f"- {block['content']}\n"
            md += "\n"

    # Decisions
    if data.get("KeyItemsDecisions", {}).get("blocks"):
        md += f"## {data['KeyItemsDecisions']['title']}\n\n"
        for block in data["KeyItemsDecisions"]["blocks"]:
            md += f"- {block['content']}\n"
        md += "\n"

    # Action Items
    if data.get("ImmediateActionItems", {}).get("blocks"):
        md += f"## {data['ImmediateActionItems']['title']}\n\n"
        for block in data["ImmediateActionItems"]["blocks"]:
            md += f"- [ ] {block['content']}\n"
        md += "\n"

    # Deadlines
    if data.get("CriticalDeadlines", {}).get("blocks"):
        md += f"## {data['CriticalDeadlines']['title']}\n\n"
        for block in data["CriticalDeadlines"]["blocks"]:
            md += f"- {block['content']}\n"
        md += "\n"

    # Next Steps
    if data.get("NextSteps", {}).get("blocks"):
        md += f"## {data['NextSteps']['title']}\n\n"
        for block in data["NextSteps"]["blocks"]:
            md += f"- {block['content']}\n"
        md += "\n"

    return md


def generate_standup_markdown(data: dict) -> str:
    """Generate markdown for daily standups"""
    md = ""

    # Individual updates
    if data.get("MeetingNotes", {}).get("sections"):
        md += "## Team Updates\n\n"
        for section in data["MeetingNotes"]["sections"]:
            if not section.get("blocks"):
                continue
            md += f"### {section['title']}\n\n"
            for block in section["blocks"]:
                md += f"{block['content']}\n"
            md += "\n"

    # Actions and deadlines
    if data.get("ImmediateActionItems", {}).get("blocks"):
        md += f"## {data['ImmediateActionItems']['title']}\n\n"
        for block in data["ImmediateActionItems"]["blocks"]:
            md += f"- [ ] {block['content']}\n"
        md += "\n"

    if data.get("CriticalDeadlines", {}).get("blocks"):
        md += f"## {data['CriticalDeadlines']['title']}\n\n"
        for block in data["CriticalDeadlines"]["blocks"]:
            md += f"- {block['content']}\n"
        md += "\n"

    return md


def generate_brainstorming_markdown(data: dict) -> str:
    """Generate markdown for brainstorming sessions"""
    md = ""

    # Ideas organized by theme
    if data.get("MeetingNotes", {}).get("sections"):
        md += "## Ideas Generated\n\n"
        for section in data["MeetingNotes"]["sections"]:
            if not section.get("blocks"):
                continue
            md += f"### {section['title']}\n\n"
            for block in section["blocks"]:
                md += f"{block['content']}\n"
            md += "\n"

    # Selected ideas and next steps
    if data.get("KeyItemsDecisions", {}).get("blocks"):
        md += f"## {data['KeyItemsDecisions']['title']}\n\n"
        for block in data["KeyItemsDecisions"]["blocks"]:
            md += f"- {block['content']}\n"
        md += "\n"

    if data.get("ImmediateActionItems", {}).get("blocks"):
        md += f"## {data['ImmediateActionItems']['title']}\n\n"
        for block in data["ImmediateActionItems"]["blocks"]:
            md += f"- [ ] {block['content']}\n"
        md += "\n"

    return md


def generate_interview_markdown(data: dict) -> str:
    """Generate markdown for interviews"""
    md = ""

    # Assessment sections
    if data.get("MeetingNotes", {}).get("sections"):
        md += "## Interview Assessment\n\n"
        for section in data["MeetingNotes"]["sections"]:
            if not section.get("blocks"):
                continue
            md += f"### {section['title']}\n\n"
            for block in section["blocks"]:
                md += f"{block['content']}\n"
            md += "\n"

    # Recommendation
    if data.get("KeyItemsDecisions", {}).get("blocks"):
        md += f"## {data['KeyItemsDecisions']['title']}\n\n"
        for block in data["KeyItemsDecisions"]["blocks"]:
            md += f"**{block['content']}**\n\n"

    # Next steps
    if data.get("ImmediateActionItems", {}).get("blocks"):
        md += f"## {data['ImmediateActionItems']['title']}\n\n"
        for block in data["ImmediateActionItems"]["blocks"]:
            md += f"- [ ] {block['content']}\n"
        md += "\n"

    return md


def generate_project_kickoff_markdown(data: dict) -> str:
    """Generate markdown for project kickoffs"""
    md = ""

    # Project details
    if data.get("MeetingNotes", {}).get("sections"):
        for section in data["MeetingNotes"]["sections"]:
            if not section.get("blocks"):
                continue
            md += f"## {section['title']}\n\n"
            for block in section["blocks"]:
                md += f"{block['content']}\n"
            md += "\n"

    # Decisions, actions, milestones
    if data.get("KeyItemsDecisions", {}).get("blocks"):
        md += f"## {data['KeyItemsDecisions']['title']}\n\n"
        for block in data["KeyItemsDecisions"]["blocks"]:
            md += f"- {block['content']}\n"
        md += "\n"

    if data.get("ImmediateActionItems", {}).get("blocks"):
        md += f"## {data['ImmediateActionItems']['title']}\n\n"
        for block in data["ImmediateActionItems"]["blocks"]:
            md += f"- [ ] {block['content']}\n"
        md += "\n"

    if data.get("CriticalDeadlines", {}).get("blocks"):
        md += f"## {data['CriticalDeadlines']['title']}\n\n"
        for block in data["CriticalDeadlines"]["blocks"]:
            md += f"- {block['content']}\n"
        md += "\n"

    return md


# --- API Endpoints (rest remains the same) ---


@router.get("/meetings/{meeting_id}/versions")
async def get_transcript_versions(
    meeting_id: str, current_user: User = Depends(get_current_user)
):
    """Get all transcript versions for a meeting."""
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        versions = await db.get_transcript_versions(meeting_id)
        return {"meeting_id": meeting_id, "versions": versions}
    except Exception as e:
        logger.error(f"Error getting transcript versions: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/meetings/{meeting_id}/versions/{version_num}")
async def get_transcript_version_content(
    meeting_id: str, version_num: int, current_user: User = Depends(get_current_user)
):
    """Get the content of a specific transcript version."""
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        content = await db.get_transcript_version_content(meeting_id, version_num)
        if content is None:
            raise HTTPException(status_code=404, detail="Version not found")
        return {
            "meeting_id": meeting_id,
            "version_num": version_num,
            "content": content,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting transcript version content: {str(e)}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/meetings/{meeting_id}/versions/{version_num}")
async def delete_transcript_version(
    meeting_id: str, version_num: int, current_user: User = Depends(get_current_user)
):
    """Delete a specific transcript version snapshot."""
    if not await rbac.can(current_user, "edit", meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        success = await db.delete_transcript_version(meeting_id, version_num)
        if not success:
            raise HTTPException(status_code=404, detail="Version not found")
        return {"message": f"Version {version_num} deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting transcript version: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-transcript")
async def process_transcript_api(
    transcript: TranscriptRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Process a transcript text with background processing"""
    try:
        # 0. Ensure meeting exists and check permissions
        meeting = await db.get_meeting(transcript.meeting_id)
        if not meeting:
            # New Meeting: Claim Ownership
            await db.save_meeting(
                meeting_id=transcript.meeting_id,
                title="Untitled Meeting",
                owner_id=current_user.email,
                workspace_id=None,
            )
            logger.info(
                f"Created new meeting {transcript.meeting_id} for owner {current_user.email}"
            )
        else:
            # Existing Meeting: Check Edit Permission
            if not await rbac.can(current_user, "edit", transcript.meeting_id):
                raise HTTPException(
                    status_code=403, detail="Permission denied to edit this meeting"
                )

        # Create new process linked to meeting_id
        process_id = await db.create_process(transcript.meeting_id)

        # Save transcript data associated with meeting_id
        await db.save_transcript(
            transcript.meeting_id,
            transcript.text,
            transcript.model,
            transcript.model_name,
            transcript.chunk_size,
            transcript.overlap,
        )

        # Use template-specific prompt if templateId is provided, otherwise use custom_prompt
        custom_prompt = transcript.custom_prompt
        if (
            hasattr(transcript, "templateId")
            and transcript.templateId
            and not custom_prompt
        ):
            custom_prompt = get_template_prompt(transcript.templateId)

        # Start background processing
        background_tasks.add_task(
            process_transcript_background,
            process_id,
            transcript,
            custom_prompt,
            current_user.email,
        )

        return JSONResponse({"message": "Processing started", "process_id": process_id})

    except Exception as e:
        logger.error(f"Error in process_transcript_api: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save-summary")
async def save_summary(
    data: SaveSummaryRequest, current_user: User = Depends(get_current_user)
):
    """Save or update meeting summary/notes"""
    if not await rbac.can(current_user, "edit", data.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to edit summary")

    try:
        logger.info(f"Saving summary for meeting {data.meeting_id}")

        # Update the summary_processes table with the new content
        await db.update_process(
            meeting_id=data.meeting_id, status="completed", result=data.summary
        )

        logger.info(f"Successfully saved summary for meeting {data.meeting_id}")
        return {"message": "Summary saved successfully"}
    except Exception as e:
        logger.error(f"Error saving summary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save-transcript")
async def save_transcript(
    data: SaveTranscriptRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Save transcript segments manually (from frontend)"""
    meeting_id = data.session_id or str(uuid.uuid4())

    try:
        # Check if meeting exists
        meeting = await db.get_meeting(meeting_id)
        if meeting:
            if not await rbac.can(current_user, "edit", meeting_id):
                raise HTTPException(status_code=403, detail="Permission denied")
        else:
            # Create new meeting
            await db.save_meeting(
                meeting_id=meeting_id,
                title=data.meeting_title,
                owner_id=current_user.email,
            )

        # Save segments (batch)
        await db.save_meeting_transcripts_batch(meeting_id, data.transcripts)

        # CRITICAL FIX: Ensure audio folder matches meeting_id
        # The recorder might have stored files under session_id. We must rename it to meeting_id
        # so that finalize_recording and diarization can find it.
        if data.session_id and data.session_id != meeting_id:
            try:
                try:
                    from ...services.audio.recorder import AudioRecorder
                except (ImportError, ValueError):
                    from services.audio.recorder import AudioRecorder

                renamed = await AudioRecorder.rename_recorder_folder(
                    data.session_id, meeting_id
                )
                if renamed:
                    logger.info(
                        f"✅ Renamed recording folder from {data.session_id} to {meeting_id}"
                    )
                else:
                    logger.warning(
                        f"Could not rename folder from {data.session_id} to {meeting_id} (might not exist or empty)"
                    )
            except Exception as rename_error:
                logger.error(f"Failed to rename recording folder: {rename_error}")

        # Trigger post-recording processing (merge, upload to GCP, cleanup) in background
        try:
            try:
                from ...services.audio.post_recording import get_post_recording_service
            except (ImportError, ValueError):
                from services.audio.post_recording import get_post_recording_service

            post_service = get_post_recording_service()
            background_tasks.add_task(
                post_service.finalize_recording,
                meeting_id,
                trigger_diarization=False,
                user_email=current_user.email,
            )
            logger.info(f"Scheduled post-recording processing for meeting {meeting_id}")
        except Exception as post_e:
            logger.warning(f"Post-recording service unavailable: {post_e}")

        return {"message": "Transcript saved successfully", "meeting_id": meeting_id}
    except Exception as e:
        logger.error(f"Error saving transcript: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get-summary/{meeting_id}")
async def get_summary(meeting_id: str, current_user: User = Depends(get_current_user)):
    """Get the summary for a given meeting ID"""
    if not await rbac.can(current_user, "view", meeting_id):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        result = await db.get_transcript_data(meeting_id)
        if not result:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "meetingName": None,
                    "meeting_id": meeting_id,
                    "data": None,
                    "start": None,
                    "end": None,
                    "error": "Meeting ID not found",
                },
            )

        status = result.get("status", "unknown").lower()

        # Parse result data if available
        summary_data = None
        if result.get("result"):
            try:
                if isinstance(result["result"], dict):
                    summary_data = result["result"]
                else:
                    parsed_result = json.loads(result["result"])
                    if isinstance(parsed_result, str):
                        summary_data = json.loads(parsed_result)
                    else:
                        summary_data = parsed_result
            except Exception as e:
                logger.error(f"Error parsing summary data: {e}")
                status = "failed"

        # Transform summary data into frontend format if available
        transformed_data = {}
        if isinstance(summary_data, dict) and status == "completed":
            transformed_data["MeetingName"] = summary_data.get("MeetingName", "")
            if "markdown" in summary_data:
                transformed_data["markdown"] = summary_data["markdown"]

            # Map backend sections
            section_mapping = {}
            for backend_key, frontend_key in section_mapping.items():
                if backend_key in summary_data:
                    transformed_data[frontend_key] = summary_data[backend_key]

            if "MeetingNotes" in summary_data:
                transformed_data["MeetingNotes"] = summary_data["MeetingNotes"]

        return JSONResponse(
            content={
                "status": status,
                "meetingName": transformed_data.get("MeetingName"),
                "meeting_id": meeting_id,
                "data": transformed_data,
                "start": result.get("start_time").isoformat()
                if result.get("start_time")
                else None,
                "end": result.get("end_time").isoformat()
                if result.get("end_time")
                else None,
            }
        )

    except Exception as e:
        logger.error(f"Error getting summary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-detailed-notes")
async def generate_detailed_notes(
    request: GenerateNotesRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Generates detailed meeting notes using Gemini."""
    try:
        if not await rbac.can(current_user, "ai_interact", request.meeting_id):
            raise HTTPException(
                status_code=403, detail="Permission denied to generate notes"
            )

        logger.info(
            f"Generating detailed notes for meeting {request.meeting_id} using template {request.template_id}"
        )

        # 1. Fetch meeting transcripts from the database
        meeting_data = await db.get_meeting(request.meeting_id)
        if not meeting_data or not meeting_data.get("transcripts"):
            raise HTTPException(
                status_code=404, detail="Meeting or transcripts not found."
            )

        transcripts = meeting_data["transcripts"]
        full_transcript_text = "\n".join([t["text"] for t in transcripts])

        if not full_transcript_text.strip():
            raise HTTPException(status_code=400, detail="Transcript text is empty.")

        meeting_title = meeting_data.get("title", "Untitled Meeting")

        # 2. Start background processing (non-blocking)
        background_tasks.add_task(
            generate_notes_with_gemini_background,
            request.meeting_id,
            full_transcript_text,
            request.template_id,
            meeting_title,
            "",
            current_user.email,
        )

        return JSONResponse(
            content={
                "message": "Notes generation started",
                "meeting_id": request.meeting_id,
                "template_id": request.template_id,
                "status": "processing",
            }
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error starting notes generation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/meetings/{meeting_id}/generate-notes")
async def generate_notes_for_meeting(
    meeting_id: str,
    request: GenerateNotesRequest = None,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
):
    """Generate meeting notes for a specific meeting using the selected template."""
    if not await rbac.can(current_user, "ai_interact", meeting_id):
        raise HTTPException(
            status_code=403, detail="Permission denied to generate notes"
        )

    try:
        actual_meeting_id = meeting_id
        template_id = "standard_meeting"
        custom_context = ""

        if request:
            template_id = request.template_id or "standard_meeting"
            custom_context = request.custom_context or ""

        logger.info(
            f"Generating notes for meeting {actual_meeting_id} using template {template_id}"
        )

        # 1. Fetch meeting transcripts
        # Check if transcript is provided in request (e.g. from frontend with specific version/edits)
        if request and request.transcript and request.transcript.strip():
            logger.info(f"Using provided transcript text for meeting {actual_meeting_id}")
            full_transcript_text = request.transcript
            # We still need meeting title
            meeting_data = await db.get_meeting(actual_meeting_id)
            meeting_title = meeting_data.get("title", "Untitled Meeting") if meeting_data else "Untitled Meeting"
        else:
            # Fallback to fetching from DB
            meeting_data = await db.get_meeting(actual_meeting_id)
            if not meeting_data or not meeting_data.get("transcripts"):
                raise HTTPException(
                    status_code=404, detail="Meeting or transcripts not found."
                )

            transcripts = meeting_data["transcripts"]
            # Default joining without speaker labels (historical behavior)
            full_transcript_text = "\n".join([t["text"] for t in transcripts])

        if not full_transcript_text.strip():
            raise HTTPException(status_code=400, detail="Transcript text is empty.")

        meeting_title = meeting_data.get("title", "Untitled Meeting")

        # 2. Start background processing (non-blocking)
        background_tasks.add_task(
            generate_notes_with_gemini_background,
            actual_meeting_id,
            full_transcript_text,
            template_id,
            meeting_title,
            custom_context,
            current_user.email,
        )

        return JSONResponse(
            content={
                "message": "Notes generation started",
                "meeting_id": actual_meeting_id,
                "template_id": template_id,
                "status": "processing",
            }
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(
            f"Error starting notes generation for meeting {meeting_id}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refine-notes")
async def refine_notes(
    request: RefineNotesRequest, current_user: User = Depends(get_current_user)
):
    """
    Refine existing meeting notes based on user instructions and transcript context.
    Streams the refined notes back.
    """
    if not await rbac.can(current_user, "ai_interact", request.meeting_id):
        raise HTTPException(status_code=403, detail="Permission denied to refine notes")

    try:
        logger.info(
            f"Refining notes for meeting {request.meeting_id} with instruction: {request.user_instruction[:50]}..."
        )

        # 1. Fetch meeting transcripts for context
        meeting_data = await db.get_meeting(request.meeting_id)
        full_transcript = ""
        if meeting_data and meeting_data.get("transcripts"):
            full_transcript = "\n".join(
                [t["text"] for t in meeting_data["transcripts"]]
            )

        # 2. Construct Prompt
        refine_prompt = f"""You are an expert meeting notes editor.
Your task is to REFINE the Current Meeting Notes based strictly on the User Instruction and the provided Context (Transcript).

Context (Meeting Transcript):
---
{full_transcript[:30000]} {(len(full_transcript) > 30000) and "...(truncated)" or ""}
---

Current Meeting Notes:
---
{request.current_notes}
---

User Instruction: {request.user_instruction}

Guidelines:
1. You MUST start your response with a detailed bulleted list of changes made.
2. You MUST then output exactly: "|||SEPARATOR|||" (without quotes).
3. After the separator, provide the FULL updated notes content.
"""

        chat_service = ChatService(db)

        generator = await chat_service.refine_notes(
            notes=request.current_notes,
            instruction=request.user_instruction,
            transcript_context=full_transcript,
            model=request.model,
            model_name=request.model_name,
            user_email=current_user.email,
        )

        return StreamingResponse(generator, media_type="text/plain")

    except Exception as e:
        logger.error(f"Error in refine_notes: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))