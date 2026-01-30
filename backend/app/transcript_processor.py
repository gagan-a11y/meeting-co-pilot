from pydantic import BaseModel
from typing import List, Tuple, Literal, Optional, Dict, Any
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.providers.anthropic import AnthropicProvider
# Gemini is used directly via google.generativeai, not pydantic-ai

import logging
import os
from dotenv import load_dotenv
from db import DatabaseManager
from ollama import chat
import asyncio
from ollama import AsyncClient
from duckduckgo_search import DDGS


# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()  # Load environment variables from .env file

db = DatabaseManager()


class Block(BaseModel):
    """Represents a block of content in a section.

    Block types must align with frontend rendering capabilities:
    - 'text': Plain text content
    - 'bullet': Bulleted list item
    - 'heading1': Large section heading
    - 'heading2': Medium section heading

    Colors currently supported:
    - 'gray': Gray text color
    - '' or any other value: Default text color
    """

    id: str
    type: Literal["bullet", "heading1", "heading2", "text"]
    content: str
    color: str  # Frontend currently only uses 'gray' or default


class Section(BaseModel):
    """Represents a section in the meeting summary"""

    title: str
    blocks: List[Block]


class MeetingNotes(BaseModel):
    """Represents the meeting notes"""

    meeting_name: str
    sections: List[Section]


class People(BaseModel):
    """Represents the people in the meeting. Always have this part in the output. Title - Person Name (Role, Details)"""

    title: str
    blocks: List[Block]


class SummaryResponse(BaseModel):
    """Represents the meeting summary response based on a section of the transcript"""

    MeetingName: str
    People: People
    SessionSummary: Section
    CriticalDeadlines: Section
    KeyItemsDecisions: Section
    ImmediateActionItems: Section
    NextSteps: Section
    MeetingNotes: MeetingNotes


# --- Main Class Used by main.py ---


class TranscriptProcessor:
    """Handles the processing of meeting transcripts using AI models."""

    def __init__(self):
        """Initialize the transcript processor."""
        logger.info("TranscriptProcessor initialized.")
        self.db = DatabaseManager()
        self.active_clients = []  # Track active Ollama client sessions

    async def process_transcript(
        self,
        text: str,
        model: str,
        model_name: str,
        chunk_size: int = 5000,
        overlap: int = 1000,
        custom_prompt: str = "",
        user_email: Optional[str] = None,
    ) -> Tuple[int, List[str]]:
        """
        Process transcript text into chunks and generate structured summaries for each chunk using an AI model.

        Args:
            text: The transcript text.
            model: The AI model provider ('claude', 'ollama', 'groq', 'openai').
            model_name: The specific model name.
            chunk_size: The size of each text chunk.
            overlap: The overlap between consecutive chunks.
            custom_prompt: A custom prompt to use for the AI model.

        Returns:
            A tuple containing:
            - The number of chunks processed.
            - A list of JSON strings, where each string is the summary of a chunk.
        """

        logger.info(
            f"Processing transcript (length {len(text)}) with model provider={model}, model_name={model_name}, chunk_size={chunk_size}, overlap={overlap}"
        )

        all_json_data = []
        agent = None  # Define agent variable
        llm = None  # Define llm variable

        try:
            # Select and initialize the AI model and agent
            if model == "claude":
                api_key = await db.get_api_key("claude", user_email=user_email)
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY environment variable not set")
                llm = AnthropicModel(
                    model_name, provider=AnthropicProvider(api_key=api_key)
                )
                logger.info(f"Using Claude model: {model_name}")
            elif model == "ollama":
                # Use environment variable for Ollama host configuration
                ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                ollama_base_url = f"{ollama_host}/v1"
                ollama_model = OpenAIModel(
                    model_name=model_name,
                    provider=OpenAIProvider(base_url=ollama_base_url),
                )
                llm = ollama_model
                if model_name.lower().startswith(
                    "phi4"
                ) or model_name.lower().startswith("llama"):
                    chunk_size = 10000
                    overlap = 1000
                else:
                    chunk_size = 30000
                    overlap = 1000
                logger.info(f"Using Ollama model: {model_name}")
            elif model == "groq":
                api_key = await db.get_api_key("groq", user_email=user_email)
                if not api_key:
                    raise ValueError("GROQ_API_KEY environment variable not set")
                llm = GroqModel(model_name, provider=GroqProvider(api_key=api_key))
                logger.info(f"Using Groq model: {model_name}")
            # --- ADD OPENAI SUPPORT HERE ---
            elif model == "openai":
                api_key = await db.get_api_key("openai", user_email=user_email)
                if not api_key:
                    raise ValueError("OPENAI_API_KEY environment variable not set")
                llm = OpenAIModel(model_name, provider=OpenAIProvider(api_key=api_key))
                logger.info(f"Using OpenAI model: {model_name}")
            # --- END OPENAI SUPPORT ---
            # --- GEMINI SUPPORT ---
            elif model == "gemini":
                api_key = await db.get_api_key("gemini", user_email=user_email)
                if not api_key:
                    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                if not api_key:
                    raise ValueError("Gemini API key not found")

                import google.generativeai as genai

                genai.configure(api_key=api_key)
                # Use gemini-2.0-flash for speed and large context
                model_name = model_name or "gemini-2.0-flash"
                llm = genai.GenerativeModel(model_name)
                logger.info(f"Using Gemini model: {model_name}")
            # --- END GEMINI SUPPORT ---
            else:
                logger.error(f"Unsupported model provider requested: {model}")
                raise ValueError(f"Unsupported model provider: {model}")

            # Initialize the agent with the selected LLM (for non-Gemini models)
            if model != "gemini":
                agent = Agent(
                    llm,
                    result_type=SummaryResponse,
                    result_retries=2,
                )
                logger.info(f"Pydantic-AI Agent initialized for {model}.")

            # Split transcript into chunks
            step = chunk_size - overlap
            if step <= 0:
                logger.warning(
                    f"Overlap ({overlap}) >= chunk_size ({chunk_size}). Adjusting overlap."
                )
                overlap = max(0, chunk_size - 100)
                step = chunk_size - overlap

            chunks = [text[i : i + chunk_size] for i in range(0, len(text), step)]
            num_chunks = len(chunks)
            logger.info(f"Split transcript into {num_chunks} chunks.")

            for i, chunk in enumerate(chunks):
                logger.info(f"Processing chunk {i + 1}/{num_chunks}...")
                try:
                    # Run the agent or Gemini to get the structured summary for the chunk
                    if model == "gemini":
                        prompt = f"""Given the following meeting transcript chunk, extract the relevant information according to the required JSON structure.
                        
                        IMPORTANT: 
                        1. Return ONLY valid JSON. No markdown formatting, no code blocks.
                        2. Block types must be one of: 'text', 'bullet', 'heading1', 'heading2'
                        3. Sections: MeetingName, People, SessionSummary, CriticalDeadlines, KeyItemsDecisions, ImmediateActionItems, NextSteps, MeetingNotes.
                        
                        Transcript Chunk:
                        ---
                        {chunk}
                        ---
                        
                        Context:
                        ---
                        {custom_prompt}
                        ---
                        """

                        # Use Gemini for structured output
                        response = await llm.generate_content_async(
                            prompt,
                            generation_config={
                                "response_mime_type": "application/json"
                            },
                        )
                        chunk_summary_json = response.text
                        all_json_data.append(chunk_summary_json)
                        logger.info(
                            f"Successfully generated Gemini summary for chunk {i + 1}."
                        )
                        continue

                    elif model != "ollama":
                        summary_result = await agent.run(
                            f"""Given the following meeting transcript chunk, extract the relevant information according to the required JSON structure. If a specific section (like Critical Deadlines) has no relevant information in this chunk, return an empty list for its 'blocks'. Ensure the output is only the JSON data.

                            IMPORTANT: Block types must be one of: 'text', 'bullet', 'heading1', 'heading2'
                            - Use 'text' for regular paragraphs
                            - Use 'bullet' for list items
                            - Use 'heading1' for major headings
                            - Use 'heading2' for subheadings
                            
                            For the color field, use 'gray' for less important content or '' (empty string) for default.

                            Transcript Chunk:
                            ---
                        {chunk}
                        ---

                        Please capture all relevant action items. Transcription can have spelling mistakes. correct it if required. context is important.
                        
                        While generating the summary, please add the following context:
                        ---
                        {custom_prompt}
                        ---
                        Make sure the output is only the JSON data.
                        """,
                        )
                    else:
                        logger.info(
                            f"Using Ollama model: {model_name} and chunk size: {chunk_size} with overlap: {overlap}"
                        )
                        response = await self.chat_ollama_model(
                            model_name, chunk, custom_prompt
                        )

                        # Check if response is already a SummaryResponse object or a string that needs validation
                        if isinstance(response, SummaryResponse):
                            summary_result = response
                        else:
                            # If it's a string (JSON), validate it
                            summary_result = SummaryResponse.model_validate_json(
                                response
                            )

                        logger.info(
                            f"Summary result for chunk {i + 1}: {summary_result}"
                        )
                        logger.info(
                            f"Summary result type for chunk {i + 1}: {type(summary_result)}"
                        )

                    if hasattr(summary_result, "data") and isinstance(
                        summary_result.data, SummaryResponse
                    ):
                        final_summary_pydantic = summary_result.data
                    elif isinstance(summary_result, SummaryResponse):
                        final_summary_pydantic = summary_result
                    else:
                        logger.error(
                            f"Unexpected result type from agent for chunk {i + 1}: {type(summary_result)}"
                        )
                        continue  # Skip this chunk

                    # Convert the Pydantic model to a JSON string
                    chunk_summary_json = final_summary_pydantic.model_dump_json()
                    all_json_data.append(chunk_summary_json)
                    logger.info(f"Successfully generated summary for chunk {i + 1}.")

                except Exception as chunk_error:
                    logger.error(
                        f"Error processing chunk {i + 1}: {chunk_error}", exc_info=True
                    )

            logger.info(f"Finished processing all {num_chunks} chunks.")
            return num_chunks, all_json_data

        except Exception as e:
            logger.error(f"Error during transcript processing: {str(e)}", exc_info=True)
            raise

    async def chat_ollama_model(
        self, model_name: str, transcript: str, custom_prompt: str
    ):
        message = {
            "role": "system",
            "content": f"""
        Given the following meeting transcript chunk, extract the relevant information according to the required JSON structure. If a specific section (like Critical Deadlines) has no relevant information in this chunk, return an empty list for its 'blocks'. Ensure the output is only the JSON data.

        Transcript Chunk:
            ---
            {transcript}
            ---
        Please capture all relevant action items. Transcription can have spelling mistakes. correct it if required. context is important.
        
        While generating the summary, please add the following context:
        ---
        {custom_prompt}
        ---

        Make sure the output is only the JSON data.
    
        """,
        }

        # Create a client and track it for cleanup
        ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

        # Use async context manager to ensure client is closed
        async with AsyncClient(host=ollama_host) as client:
            self.active_clients.append(client)
            try:
                # Increase timeout for long context processing
                # Note: ollama client uses httpx, we can try to pass timeout if supported or rely on default
                response = await client.chat(
                    model=model_name,
                    messages=[message],
                    stream=True,
                    format=SummaryResponse.model_json_schema(),
                )

                full_response = ""
                async for part in response:
                    content = part["message"]["content"]
                    # Remove stdout print to avoid log noise/issues
                    # print(content, end='', flush=True)
                    full_response += content

                try:
                    summary = SummaryResponse.model_validate_json(full_response)
                    # logger.debug(f"Ollama summary: {summary.model_dump_json(indent=2)}")
                    return summary
                except Exception as e:
                    logger.error(
                        f"Error parsing Ollama response: {e}. Raw response: {full_response[:200]}..."
                    )
                    return full_response

            except asyncio.CancelledError:
                logger.info("Ollama request was cancelled during shutdown")
                raise
            except Exception as e:
                logger.error(f"Error in Ollama chat: {e}")
                raise
            finally:
                # Remove the client from active clients list as it's being closed by context manager
                if client in self.active_clients:
                    self.active_clients.remove(client)

    async def _needs_linked_context(
        self, question: str, current_context_snippet: str
    ) -> bool:
        """
        Determine if the question needs linked meeting context using keyword detection.

        Since this is an internal product, users are instructed to use specific keywords
        when they want to search in linked meetings (similar to web search triggers).

        Returns True if the question contains linked meeting keywords.
        """
        question_lower = question.lower()

        # Keywords that trigger linked meeting search
        # Users should use these keywords to explicitly request cross-meeting context
        cross_meeting_keywords = [
            "search in linked meetings",
            "linked meetings",
            "search linked",
            "previous meeting",
            "last meeting",
            "other meeting",
            "earlier meeting",
            "compare",
            "comparison",
            "different from",
            "changed since",
            "history",
            "past",
            "previously discussed",
            "follow up",
            "follow-up",
            "what did we say",
            "what was said",
            "mentioned before",
            "discussed earlier",
        ]

        for keyword in cross_meeting_keywords:
            if keyword in question_lower:
                logger.info(
                    f"Linked context: keyword '{keyword}' detected, will fetch linked meeting context"
                )
                return True

        # No keyword match - don't fetch linked context
        logger.info(
            "Linked context: no trigger keyword detected, skipping linked meeting search"
        )
        return False

    async def search_web(self, query: str, user_email: Optional[str] = None) -> str:
        """
        Real web search using SerpAPI (Google) + crawling + Gemini summarization.
        1. Search Google via SerpAPI for URLs
        2. Crawl and extract content from pages
        3. Use Gemini to synthesize and summarize with citations
        """
        logger.info(f"Real web search for: {query}")
        try:
            import httpx
            import trafilatura
            import google.generativeai as genai
            import asyncio
            import os

            # Step 1: Search Google via SerpAPI
            SERPAPI_KEY = os.getenv("SERPAPI_KEY")

            async def serpapi_search():
                try:
                    from serpapi import GoogleSearch

                    params = {
                        "q": query,
                        "api_key": SERPAPI_KEY,
                        "num": 5,
                        "hl": "en",  # English language
                        "gl": "us",  # US region
                    }

                    # Run in thread pool since SerpAPI is sync
                    def do_search():
                        search = GoogleSearch(params)
                        results = search.get_dict()
                        return results.get("organic_results", [])

                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, do_search)
                except Exception as e:
                    logger.error(f"SerpAPI search failed: {e}")
                    return []

            search_results = await serpapi_search()

            if not search_results:
                return f"No search results found for '{query}'."

            logger.info(f"SerpAPI found {len(search_results)} results")

            # Step 2: Crawl pages and extract content
            async def fetch_and_extract(url: str) -> dict:
                try:
                    async with httpx.AsyncClient(
                        timeout=10.0, follow_redirects=True
                    ) as client:
                        response = await client.get(
                            url,
                            headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                            },
                        )
                        if response.status_code == 200:
                            html = response.text
                            # Extract main content using trafilatura
                            text = trafilatura.extract(
                                html, include_comments=False, include_tables=True
                            )
                            if text and len(text) > 100:
                                return {
                                    "url": url,
                                    "content": text[:2000],
                                    "success": True,
                                }
                except Exception as e:
                    logger.warning(f"Failed to crawl {url}: {e}")
                return {"url": url, "content": "", "success": False}

            # Crawl pages in parallel - SerpAPI uses 'link' instead of 'href'
            crawl_tasks = [
                fetch_and_extract(r.get("link", "")) for r in search_results[:4]
            ]
            crawled = await asyncio.gather(*crawl_tasks)

            # Collect successful extractions
            sources = []
            for i, result in enumerate(crawled):
                if result["success"] and result["content"]:
                    title = search_results[i].get("title", "Unknown")
                    sources.append(
                        {
                            "title": title,
                            "url": result["url"],
                            "content": result["content"],
                        }
                    )

            if not sources:
                # Fallback: use SerpAPI snippets
                sources = [
                    {
                        "title": r.get("title", "Unknown"),
                        "url": r.get("link", ""),
                        "content": r.get("snippet", ""),
                    }
                    for r in search_results[:3]
                ]

            logger.info(f"Extracted content from {len(sources)} sources")

            # Step 3: Use Gemini to synthesize
            api_key = await db.get_api_key("gemini", user_email=user_email)
            if not api_key:
                import os

                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

            if not api_key:
                return "❌ Gemini API key not configured."

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")

            # Format sources for context
            sources_text = ""
            for i, src in enumerate(sources, 1):
                sources_text += f"\n[Source {i}: {src['title']}]\nURL: {src['url']}\nContent:\n{src['content']}\n---\n"

            prompt = f"""You are a research assistant. Based on the following web sources, provide a comprehensive answer to the query.

Query: {query}

Web Sources:
{sources_text}

Instructions:
1. Synthesize information from the sources provided
2. Cite sources inline using [Source N] format
3. Be factual - only use information from the sources
4. Provide specific data, numbers, and comparisons where available
5. Format with clear headings and bullet points

End with a "Sources" section listing all referenced URLs."""

            from google.generativeai.types import HarmCategory, HarmBlockThreshold

            response = await model.generate_content_async(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0.3,  # Lower for more factual
                    max_output_tokens=2048,
                ),
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                },
            )

            if response and response.text:
                return f"**🔍 Web Research Results:**\n\n{response.text}"
            else:
                return "Failed to generate summary from sources."

        except Exception as e:
            logger.error(f"Real web search failed: {e}", exc_info=True)
            return f"Web search failed: {str(e)}"

    async def _needs_web_search(
        self, question: str, context_snippet: str, user_email: Optional[str] = None
    ) -> bool:
        """
        Use gemini-pro model to quickly determine if the question needs a web search.
        Returns True if the question requires external/real-time information.
        """
        # First check if context is empty - if so, more likely to need web search
        has_context = bool(context_snippet and len(context_snippet.strip()) > 50)

        try:
            api_key = await db.get_api_key("gemini", user_email=user_email)
            if not api_key:
                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                return False  # Default to no search if we can't classify

            import google.generativeai as genai

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")

            classifier_prompt = f"""You are a classifier. Determine if this question requires REAL-TIME WEB SEARCH or can be answered from meeting context.

Question: "{question}"

Meeting context available: {"Yes, about: " + context_snippet[:200] if has_context else "No meeting context"}

Answer ONLY "SEARCH" or "MEETING":
- "SEARCH" if question asks about: weather, current events, latest news, stock prices, sports scores, real-time data, or anything NOT in meeting notes
- "MEETING" if question can be answered from meeting discussion, action items, decisions, or participants"""

            response = model.generate_content(classifier_prompt)

            answer = response.text.strip().upper()
            needs_search = "SEARCH" in answer
            logger.info(
                f"Web search classifier: '{answer}' -> needs_web_search={needs_search}"
            )
            return needs_search

        except Exception as e:
            logger.warning(f"Web search classifier failed: {e}")
            return False

    async def _reformulate_query(
        self,
        question: str,
        history: List[Dict[str, str]],
        user_email: Optional[str] = None,
    ) -> str:
        """
        Reformulate the user's question into a standalone query using conversation history.
        Resolves pronouns like "it", "that", "these things" to their actual context.
        """
        if not history or len(history) == 0:
            return question

        try:
            # We use Gemini for fast reformulation
            api_key = await db.get_api_key("gemini", user_email=user_email)
            if not api_key:
                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                return question

            import google.generativeai as genai

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")

            # Format recent history (last 3 turns is usually enough for context)
            recent_history = history[-6:] if len(history) > 6 else history
            history_text = ""
            for msg in recent_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")[:300]  # Truncate for speed
                history_text += f"{role.upper()}: {content}\n"

            prompt = f"""Given the conversation history, rewrite the last user question to be a concise, keyword-focused search query suitable for a search engine (like Google).
Resolve pronouns (it, that, they) and vague references.
If the user refers to "the previous question", replace it with the ACTUAL topic of the previous question.
Remove conversational filler like "can you tell me", "please search for", "how to do", etc., unless "how to" is part of the technical query.

Examples:
History: User: "How to fix deployment?" AI: "Use load balancing."
User: "Search web for that."
Result: "load balancing deployment fix"

History: User: "What is the price of BTC?" AI: "$95k."
User: "I meant search on web for the previous question."
Result: "current bitcoin price"

History: User: "can you tell me how to do proper load testing"
Result: "proper load testing guide best practices"

Do NOT answer the question. Just rewrite it as a search query.

History:
{history_text}

Last User Question: "{question}"

Search Query:"""

            response = await model.generate_content_async(prompt)
            reformulated = response.text.strip()

            # Sanity check: if result is too long or empty, fallback
            if not reformulated or len(reformulated) > len(question) * 4:
                return question

            logger.info(f"Query Reformulation: '{question}' -> '{reformulated}'")
            return reformulated

        except Exception as e:
            logger.warning(f"Query reformulation failed: {e}")
            return question

    async def chat_about_meeting(
        self,
        context: str,
        question: str,
        model: str,
        model_name: str,
        allowed_meeting_ids: Optional[List[str]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        user_email: Optional[str] = None,
    ):
        """
        Ask a question about the meeting context with cross-meeting search capabilities.
        Returns a streaming response generator.
        """
        logger.info(f"Chat request: '{question}' using model {model}:{model_name}")

        # === 0. CONTEXTUAL REFORMULATION ===
        # If we have history, the user's question might be vague ("how do i do that?").
        # We rewrite it to be specific ("how do i perform load testing?") before checking for search triggers.
        reformulated_question = question
        if history and len(history) > 0:
            reformulated_question = await self._reformulate_query(
                question, history, user_email
            )

        # Use reformulated question for logic, but keep original for the final prompt if needed
        # Actually, for the final prompt, the original + history is fine for the LLM.
        # But for "Search Triggers", we MUST use the reformulated version.
        logic_question = reformulated_question

        # Initialize context containers
        web_context = ""
        cross_meeting_context = ""
        search_status_msg = ""

        # === 1. WEB SEARCH STRATEGY ===
        question_lower = logic_question.lower().strip()

        # A. Explicit Triggers (User commands it)
        web_search_triggers = [
            "search on web",
            "find on web",
            "search for",
            "google for",
        ]
        needs_search = False
        search_query = logic_question  # Default to reformulated question

        # SPECIAL HANDLING: Check if user is asking to search for a "previous" thing explicitly
        # If so, rely 100% on the reformulated query, do NOT try to string-split the original query.
        meta_references = [
            "previous question",
            "last question",
            "that question",
            "earlier question",
        ]
        is_meta_query = any(ref in question_lower for ref in meta_references)

        for trigger in web_search_triggers:
            if trigger in question_lower:
                logger.info(f"Auto-detected explicit web search trigger: '{trigger}'")
                needs_search = True

                if is_meta_query:
                    # If user said "search for previous question", the REFORMULATED query (logic_question)
                    # should already be "Search for [Topic]". We just want the [Topic] part.
                    # But often reformulated query is just "[Topic]".
                    # Let's try to clean the REFORMULATED query.
                    clean_reformulated = logic_question.lower()
                    for t in web_search_triggers:
                        clean_reformulated = clean_reformulated.replace(t, "")
                    search_query = clean_reformulated.strip()
                    if len(search_query) < 3:
                        search_query = logic_question
                else:
                    # Standard behavior: Clean query from the REFORMULATED question
                    # This ensures "search for it" -> reformulated "search for [topic]" -> extracted "[topic]"
                    search_query_lower = logic_question.lower()

                    # Logic: Find where the trigger appears in the reformulated string
                    # If reformulated is "Search for Apple", removing "Search for" leaves "Apple".
                    # If reformulated is just "Apple" (because LLM removed the prefix), replace does nothing.
                    temp_query = search_query_lower
                    for t in web_search_triggers:
                        if t in temp_query:
                            temp_query = temp_query.replace(t, "")

                    search_query = temp_query.strip()
                    if len(search_query) < 3:
                        search_query = logic_question
                break

        # B. Implicit Triggers (Router decides)
        if not needs_search:
            # Only run classifier if we have some context (otherwise it's definitely a general question or needs search)
            # Actually, if context is empty, we arguably SHOULD search web for general knowledge.
            # Let's trust the classifier using the REFORMULATED question.
            needs_search = await self._needs_web_search(
                logic_question, context[:1000] if context else "", user_email=user_email
            )
            if needs_search:
                logger.info("Router decided this question needs Web Search.")
                search_query = logic_question

        # Execute Search if needed
        if needs_search:
            search_status_msg = f"🔍 Searching web for: *{search_query}*...\n\n"
            try:
                web_result = await self.search_web(search_query, user_email=user_email)
                if "Failed" not in web_result and "No search results" not in web_result:
                    web_context = f"\n\n=== EXTERNAL WEB CONTEXT ===\n{web_result}\n"
                else:
                    logger.warning(
                        f"Web search yielded no useful results: {web_result}"
                    )
            except Exception as e:
                logger.error(f"Web search failed during chat: {e}")

        # === 2. GLOBAL MEETING SEARCH STRATEGY ===
        global_search_triggers = [
            "search all meetings",
            "search in all meetings",
            "search globally",
            "global search",
            "find in all meetings",
            "search across meetings",
            "search in meetings",
            "search meetings",
            "search all",
        ]

        allow_global_search = False
        for trigger in global_search_triggers:
            if trigger in question_lower:
                logger.info(f"Auto-detected global meeting search trigger: '{trigger}'")
                allow_global_search = True
                break

        # === 3. FETCH ADDITIONAL CONTEXT ===

        # A. Global Search
        if allow_global_search:
            try:
                # NOTE: Vector DB might be disabled. Check stats first.
                from vector_store import search_context, get_collection_stats

                stats = get_collection_stats()
                # Check if available AND has data (count > 0)
                if stats.get("status") == "available":
                    # 20 chunks for global search across all meetings
                    # Use reformulated question for better search relevance
                    results = await search_context(
                        query=logic_question,
                        n_results=20,
                        allowed_meeting_ids=None,  # Search all meetings
                    )
                    logger.info(
                        f"Global meeting search: {len(results) if results else 0} chunks found"
                    )
                    if results:
                        cross_meeting_context += (
                            "\n\nRelevant Context from All Meetings (Global Search):\n"
                        )
                        for r in results:
                            source = f"{r.get('meeting_title', 'Unknown')} ({r.get('meeting_date', 'Unknown')})"
                            text = r.get("text", "").strip()
                            cross_meeting_context += f"- [{source}]: {text}\n"
            except Exception as e:
                logger.warning(f"Failed to perform global meeting search: {e}")

        # B. Linked Meetings (Full transcripts)
        elif allowed_meeting_ids and len(allowed_meeting_ids) > 0:
            # Check if user is asking about linked meetings
            needs_linked = await self._needs_linked_context(
                logic_question, context[:1000] if context else ""
            )

            if needs_linked:
                logger.info(
                    f"Fetching full transcripts for {len(allowed_meeting_ids)} linked meetings"
                )
                try:
                    cross_meeting_context += (
                        "\n\nFULL TRANSCRIPTS FROM LINKED MEETINGS:\n"
                    )
                    for meeting_id in allowed_meeting_ids:
                        meeting_data = await self.db.get_meeting(meeting_id)
                        if meeting_data:
                            meeting_title = meeting_data.get("title", "Unknown Meeting")
                            meeting_date = meeting_data.get(
                                "created_at", "Unknown Date"
                            )
                            transcripts = meeting_data.get("transcripts", [])

                            full_transcript = "\n".join(
                                [t.get("text", "") for t in transcripts]
                            )

                            if full_transcript.strip():
                                cross_meeting_context += (
                                    f"\n=== [{meeting_title}] ({meeting_date}) ===\n"
                                )
                                cross_meeting_context += full_transcript + "\n"
                except Exception as e:
                    logger.warning(f"Failed to fetch linked meeting transcripts: {e}")

        # === 4. CONSTRUCT PROMPT ===

        # Format history
        history_text = ""
        if history and len(history) > 0:
            history_text = "\nConversation History:\n"
            selected_history = (
                history if len(history) <= 10 else history[:2] + history[-8:]
            )
            for msg in selected_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")[:1000]
                history_text += f"{role.upper()}: {content}\n"

        system_prompt = f"""You are a helpful meeting assistant. Use the provided context to answer questions accurately.

RULES:
1. Answer based on the meeting context provided below - use ALL relevant information from both current and linked meetings.
2. If EXTERNAL WEB CONTEXT is provided, use it to fact-check, elaborate, or answer questions not covered by the meeting.
3. CITATIONS:
   - If citing the meeting, use [Meeting].
   - If citing a web source, use the format [Source N] or [Domain].
   - If citing a linked meeting, use [Meeting Name].
4. Do NOT invent information. If the answer isn't in any context, say "I don't have that information."
5. Be helpful and thorough.

CURRENT MEETING CONTEXT:
---
{context}
---
{cross_meeting_context}
{web_context}
{history_text}

USER QUESTION: {question}
"""

        # === 5. STREAM RESPONSE ===
        # We wrap the model stream to optionally inject the "Searching..." status message at the start.

        async def response_wrapper(generator):
            if search_status_msg:
                yield search_status_msg
            async for chunk in generator:
                yield chunk

        try:
            # --- OLLAMA SUPPORT ---
            if model == "ollama":
                ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                client = AsyncClient(host=ollama_host)
                message = {"role": "user", "content": question}
                system_message = {"role": "system", "content": system_prompt}

                async def stream_ollama():
                    async for part in await client.chat(
                        model=model_name,
                        messages=[system_message, message],
                        stream=True,
                    ):
                        content = part["message"]["content"]
                        yield content

                return response_wrapper(stream_ollama())

            # --- GROQ SUPPORT ---
            elif model == "groq":
                api_key = await db.get_api_key("groq", user_email=user_email)
                if not api_key:
                    api_key = os.getenv("GROQ_API_KEY")
                if not api_key:
                    raise ValueError("Groq API key not found.")

                from groq import AsyncGroq

                client = AsyncGroq(api_key=api_key)

                completion_tokens = 4096
                if "8b" in model_name:
                    completion_tokens = 1024

                initial_stream = await client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    model=model_name,
                    max_tokens=completion_tokens,
                    stream=True,
                )

                async def stream_groq(stream_iter):
                    async for chunk in stream_iter:
                        content = chunk.choices[0].delta.content or ""
                        if content:
                            yield content

                return response_wrapper(stream_groq(initial_stream))

            # --- OPENAI SUPPORT ---
            elif model == "openai":
                api_key = await db.get_api_key("openai", user_email=user_email)
                if not api_key:
                    raise ValueError("OpenAI API key not found")

                from openai import AsyncOpenAI

                client = AsyncOpenAI(api_key=api_key)

                initial_stream = await client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    model=model_name,
                    stream=True,
                )

                async def stream_openai(stream_iter):
                    async for chunk in stream_iter:
                        content = chunk.choices[0].delta.content or ""
                        if content:
                            yield content

                return response_wrapper(stream_openai(initial_stream))

            # --- CLAUDE SUPPORT ---
            elif model == "claude":
                api_key = await db.get_api_key("claude", user_email=user_email)
                if not api_key:
                    raise ValueError("Anthropic API key not found")

                from anthropic import AsyncAnthropic

                client = AsyncAnthropic(api_key=api_key)

                initial_stream = await client.messages.create(
                    max_tokens=1024,
                    system=system_prompt,
                    messages=[{"role": "user", "content": question}],
                    model=model_name,
                    stream=True,
                )

                async def stream_claude(stream_iter):
                    try:
                        async for text in stream_iter.text_stream:
                            yield text
                    except Exception as e:
                        yield f"Error: {str(e)}"

                return response_wrapper(stream_claude(initial_stream))

            # --- GEMINI SUPPORT ---
            elif model == "gemini":
                api_key = await db.get_api_key("gemini", user_email=user_email)
                if not api_key:
                    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                if not api_key:
                    raise ValueError("Gemini API key not found")

                import google.generativeai as genai

                genai.configure(api_key=api_key)

                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "top_k": 64,
                    "max_output_tokens": 8192,
                }

                gen_model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=generation_config,
                    system_instruction=system_prompt,
                )

                chat_session = gen_model.start_chat(history=[])
                response = chat_session.send_message(question, stream=True)

                async def stream_gemini(response_iterator):
                    try:
                        for chunk in response_iterator:
                            if hasattr(chunk, "text") and chunk.text:
                                yield chunk.text
                    except Exception as e:
                        logger.error(f"Gemini streaming error: {e}", exc_info=True)
                        yield f"\n\nError during Gemini response: {str(e)}"

                return response_wrapper(stream_gemini(response))

            else:
                raise ValueError(f"Unsupported chat model: {model}")

        except Exception as e:
            logger.error(f"Error in chat_about_meeting: {e}", exc_info=True)
            raise e

    def cleanup(self):
        """Clean up resources used by the TranscriptProcessor."""
        logger.info("Cleaning up TranscriptProcessor resources")
        try:
            # Close database connections if any
            if hasattr(self, "db") and self.db is not None:
                # self.db.close()
                logger.info("Database connection cleanup (using context managers)")

            # Cancel any active Ollama client sessions
            if hasattr(self, "active_clients") and self.active_clients:
                logger.info(
                    f"Terminating {len(self.active_clients)} active Ollama client sessions"
                )
                for client in self.active_clients:
                    try:
                        # Close the client's underlying connection
                        if hasattr(client, "_client") and hasattr(
                            client._client, "close"
                        ):
                            asyncio.create_task(client._client.aclose())
                    except Exception as client_error:
                        logger.error(
                            f"Error closing Ollama client: {client_error}",
                            exc_info=True,
                        )
                # Clear the list
                self.active_clients.clear()
                logger.info("All Ollama client sessions terminated")
        except Exception as e:
            logger.error(
                f"Error during TranscriptProcessor cleanup: {str(e)}", exc_info=True
            )
