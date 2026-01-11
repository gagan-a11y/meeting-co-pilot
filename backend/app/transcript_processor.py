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
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
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
    type: Literal['bullet', 'heading1', 'heading2', 'text']
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
    MeetingName : str
    People : People
    SessionSummary : Section
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
    async def process_transcript(self, text: str, model: str, model_name: str, chunk_size: int = 5000, overlap: int = 1000, custom_prompt: str = "") -> Tuple[int, List[str]]:
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

        logger.info(f"Processing transcript (length {len(text)}) with model provider={model}, model_name={model_name}, chunk_size={chunk_size}, overlap={overlap}")

        all_json_data = []
        agent = None # Define agent variable
        llm = None # Define llm variable

        try:
            # Select and initialize the AI model and agent
            if model == "claude":
                api_key = await db.get_api_key("claude")
                if not api_key: raise ValueError("ANTHROPIC_API_KEY environment variable not set")
                llm = AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))
                logger.info(f"Using Claude model: {model_name}")
            elif model == "ollama":
                # Use environment variable for Ollama host configuration
                ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
                ollama_base_url = f"{ollama_host}/v1"
                ollama_model = OpenAIModel(
                    model_name=model_name, provider=OpenAIProvider(base_url=ollama_base_url)
                )
                llm = ollama_model
                if model_name.lower().startswith("phi4") or model_name.lower().startswith("llama"):
                    chunk_size = 10000
                    overlap = 1000
                else:
                    chunk_size = 30000
                    overlap = 1000
                logger.info(f"Using Ollama model: {model_name}")
            elif model == "groq":
                api_key = await db.get_api_key("groq")
                if not api_key: raise ValueError("GROQ_API_KEY environment variable not set")
                llm = GroqModel(model_name, provider=GroqProvider(api_key=api_key))
                logger.info(f"Using Groq model: {model_name}")
            # --- ADD OPENAI SUPPORT HERE ---
            elif model == "openai":
                api_key = await db.get_api_key("openai")
                if not api_key: raise ValueError("OPENAI_API_KEY environment variable not set")
                llm = OpenAIModel(model_name, provider=OpenAIProvider(api_key=api_key))
                logger.info(f"Using OpenAI model: {model_name}")
            # --- END OPENAI SUPPORT ---
            # NOTE: Gemini is not supported via pydantic-ai Agent for structured output.
            # Use Groq/Claude/OpenAI for meeting summarization. Gemini works for streaming chat.
            else:
                logger.error(f"Unsupported model provider requested: {model}")
                raise ValueError(f"Unsupported model provider: {model}")

            # Initialize the agent with the selected LLM
            agent = Agent(
                llm,
                result_type=SummaryResponse,
                result_retries=2,
            )
            logger.info("Pydantic-AI Agent initialized.")

            # Split transcript into chunks
            step = chunk_size - overlap
            if step <= 0:
                logger.warning(f"Overlap ({overlap}) >= chunk_size ({chunk_size}). Adjusting overlap.")
                overlap = max(0, chunk_size - 100)
                step = chunk_size - overlap

            chunks = [text[i:i+chunk_size] for i in range(0, len(text), step)]
            num_chunks = len(chunks)
            logger.info(f"Split transcript into {num_chunks} chunks.")

            for i, chunk in enumerate(chunks):
                logger.info(f"Processing chunk {i+1}/{num_chunks}...")
                try:
                    # Run the agent to get the structured summary for the chunk
                    if model != "ollama":
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
                        logger.info(f"Using Ollama model: {model_name} and chunk size: {chunk_size} with overlap: {overlap}")
                        response = await self.chat_ollama_model(model_name, chunk, custom_prompt)
                        
                        # Check if response is already a SummaryResponse object or a string that needs validation
                        if isinstance(response, SummaryResponse):
                            summary_result = response
                        else:
                            # If it's a string (JSON), validate it
                            summary_result = SummaryResponse.model_validate_json(response)
                            
                        logger.info(f"Summary result for chunk {i+1}: {summary_result}")
                        logger.info(f"Summary result type for chunk {i+1}: {type(summary_result)}")

                    if hasattr(summary_result, 'data') and isinstance(summary_result.data, SummaryResponse):
                         final_summary_pydantic = summary_result.data
                    elif isinstance(summary_result, SummaryResponse):
                         final_summary_pydantic = summary_result
                    else:
                         logger.error(f"Unexpected result type from agent for chunk {i+1}: {type(summary_result)}")
                         continue # Skip this chunk

                    # Convert the Pydantic model to a JSON string
                    chunk_summary_json = final_summary_pydantic.model_dump_json()
                    all_json_data.append(chunk_summary_json)
                    logger.info(f"Successfully generated summary for chunk {i+1}.")

                except Exception as chunk_error:
                    logger.error(f"Error processing chunk {i+1}: {chunk_error}", exc_info=True)

            logger.info(f"Finished processing all {num_chunks} chunks.")
            return num_chunks, all_json_data

        except Exception as e:
            logger.error(f"Error during transcript processing: {str(e)}", exc_info=True)
            raise
    
    async def chat_ollama_model(self, model_name: str, transcript: str, custom_prompt: str):
        message = {
        'role': 'system',
        'content': f'''
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
    
        ''',
        }

        # Create a client and track it for cleanup
        ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
        client = AsyncClient(host=ollama_host)
        self.active_clients.append(client)
        
        try:
            response = await client.chat(model=model_name, messages=[message], stream=True, format=SummaryResponse.model_json_schema())
            
            full_response = ""
            async for part in response:
                content = part['message']['content']
                print(content, end='', flush=True)
                full_response += content
            
            try:
                summary = SummaryResponse.model_validate_json(full_response)
                print("\n", summary.model_dump_json(indent=2), type(summary))
                return summary
            except Exception as e:
                print(f"\nError parsing response: {e}")
                return full_response
        except asyncio.CancelledError:
            logger.info("Ollama request was cancelled during shutdown")
            raise
        except Exception as e:
            logger.error(f"Error in Ollama chat: {e}")
            raise
        finally:
            # Remove the client from active clients list
            if client in self.active_clients:
                self.active_clients.remove(client)

    async def _needs_linked_context(self, question: str, current_context_snippet: str) -> bool:
        """
        Use 8b-instant model to quickly determine if the question needs linked meeting context.
        This saves tokens by avoiding unnecessary cross-meeting searches.
        
        Returns True if the question likely needs information from other meetings.
        """
        # Fast heuristic checks first (no API call needed)
        question_lower = question.lower()
        
        # Keywords that suggest cross-meeting context is needed
        cross_meeting_keywords = [
            "previous meeting", "last meeting", "other meeting", "earlier meeting",
            "compare", "comparison", "different from", "changed since", "before",
            "history", "past", "previously discussed", "follow up", "follow-up",
            "what did we say", "what was said", "mentioned before", "discussed earlier"
        ]
        
        for keyword in cross_meeting_keywords:
            if keyword in question_lower:
                logger.info(f"Classifier: keyword '{keyword}' detected, will fetch linked context")
                return True
        
        # If no obvious keywords, use Gemini for quick classification
        try:
            api_key = await db.get_api_key("gemini")
            if not api_key:
                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                # Default to True if we can't classify (safer to include context)
                return True

            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.0-flash')

            classifier_prompt = f"""You are a classifier. Given a question about a meeting, determine if the answer REQUIRES information from OTHER/PREVIOUS meetings.

Question: "{question}"

Current meeting snippet: "{current_context_snippet[:500]}"

Answer ONLY "YES" or "NO".
- "YES" if the question asks about comparisons, history, previous discussions, or references other meetings
- "NO" if the question can be answered using only the current meeting context"""

            response = model.generate_content(classifier_prompt)
            
            answer = response.text.strip().upper()
            needs_context = "YES" in answer
            logger.info(f"Classifier response: '{answer}' -> needs_linked_context={needs_context}")
            return needs_context
            
        except Exception as e:
            logger.warning(f"Classifier failed, defaulting to False: {e}")
            # Default to False (don't fetch) to save tokens
            return False

    async def search_web(self, query: str) -> str:
        """
        AI-powered web search using Gemini with grounding.
        Returns a summarized answer with citations like Perplexity.
        """
        logger.info(f"AI Web search for: {query}")
        try:
            import google.generativeai as genai
            
            # Get Gemini API key
            api_key = await db.get_api_key("gemini")
            if not api_key:
                import os
                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            
            if not api_key:
                return "❌ Gemini API key not configured. Please set GOOGLE_API_KEY or GEMINI_API_KEY."
            
            genai.configure(api_key=api_key)
            
            # Use Gemini with Google Search grounding
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            # Create a prompt that instructs Gemini to search and summarize
            search_prompt = f"""You are a research assistant. Search for information about the following query and provide a comprehensive, well-researched answer.

Query: {query}

Instructions:
1. Search for the most relevant and up-to-date information
2. Synthesize information from multiple reliable sources
3. Provide specific data, benchmarks, comparisons where available
4. Include citations with source names
5. Be factual and objective
6. Format your response clearly with sections if needed

Provide your answer in this format:
- Start with a brief summary
- Include detailed findings with specific data/numbers
- End with sources/references

Remember to cite your sources inline like [Source Name] and list them at the end."""

            # Generate response with grounding
            try:
                from google.generativeai.types import HarmCategory, HarmBlockThreshold
                
                response = await model.generate_content_async(
                    search_prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=0.7,
                        top_p=0.9,
                        max_output_tokens=2048,
                    ),
                    safety_settings={
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                )
                
                if response and response.text:
                    return f"**🔍 AI Research Results:**\n\n{response.text}"
                else:
                    return "No results found for this query."
                    
            except Exception as gen_error:
                logger.error(f"Gemini generation failed: {gen_error}")
                # Fallback to basic response
                return f"Search failed: {str(gen_error)}"
                    
        except Exception as e:
            logger.error(f"AI Web search failed: {e}")
            return f"Web search failed: {str(e)}"

    async def _needs_web_search(self, question: str, context_snippet: str) -> bool:
        """
        Use gemini-pro model to quickly determine if the question needs a web search.
        Returns True if the question requires external/real-time information.
        """
        # First check if context is empty - if so, more likely to need web search
        has_context = bool(context_snippet and len(context_snippet.strip()) > 50)
        
        try:
            api_key = await db.get_api_key("gemini")
            if not api_key:
                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                return False  # Default to no search if we can't classify
            
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            classifier_prompt = f"""You are a classifier. Determine if this question requires REAL-TIME WEB SEARCH or can be answered from meeting context.

Question: "{question}"

Meeting context available: {"Yes, about: " + context_snippet[:200] if has_context else "No meeting context"}

Answer ONLY "SEARCH" or "MEETING":
- "SEARCH" if question asks about: weather, current events, latest news, stock prices, sports scores, real-time data, or anything NOT in meeting notes
- "MEETING" if question can be answered from meeting discussion, action items, decisions, or participants"""

            response = model.generate_content(classifier_prompt)
            
            answer = response.text.strip().upper()
            needs_search = "SEARCH" in answer
            logger.info(f"Web search classifier: '{answer}' -> needs_web_search={needs_search}")
            return needs_search
            
        except Exception as e:
            logger.warning(f"Web search classifier failed: {e}")
            return False

    async def chat_about_meeting(self, context: str, question: str, model: str, model_name: str, allowed_meeting_ids: Optional[List[str]] = None, history: Optional[List[Dict[str, str]]] = None):
        """
        Ask a question about the meeting context with cross-meeting search capabilities.
        Returns a streaming response generator.
        """
        logger.info(f"Chat request: '{question}' using model {model}:{model_name}")
        
        # === AUTO-DETECT WEB SEARCH REQUESTS ===
        question_lower = question.lower().strip()
        web_search_triggers = [
            "search on web", "find on web"
        ]
        
        for trigger in web_search_triggers:
            if trigger in question_lower:
                logger.info(f"Auto-detected web search trigger: '{trigger}'")
                # Extract the actual search query
                search_query = question_lower.replace("search for", "").replace("search on web", "").replace("google", "").strip()
                if not search_query or len(search_query) < 3:
                    search_query = question
                
                # Return a generator that does the search
                async def web_search_response():
                    yield f"🔍 Searching web for: *{search_query}*...\n\n"
                    result = await self.search_web(search_query)
                    yield result
                
                return web_search_response()
        
        # === SMART CONTEXT GATING ===
        # Only fetch linked meeting context if:
        # 1. User has explicitly linked meetings (allowed_meeting_ids provided)
        # 2. The classifier determines the question needs cross-meeting context
        
        cross_meeting_context = ""
        
        # Only process linked meetings if user explicitly linked them
        if allowed_meeting_ids and len(allowed_meeting_ids) > 0:
            # Use fast 8b model to classify if we need linked context
            needs_linked = await self._needs_linked_context(question, context[:1000] if context else "")
            
            if needs_linked:
                try:
                    from vector_store import search_context, get_collection_stats
                    stats = get_collection_stats()
                    if stats.get("status") == "available":
                        # Only 5 chunks from linked meetings (reduced from 50)
                        results = await search_context(
                            query=question, 
                            n_results=5,
                            allowed_meeting_ids=allowed_meeting_ids  # Only linked meetings, no global
                        )
                        logger.info(f"Linked meeting search: {len(results) if results else 0} chunks found")
                        if results:
                            cross_meeting_context = "\n\nRelevant Context from Linked Meetings:\n"
                            for r in results:
                                source = f"{r.get('meeting_title', 'Unknown')} ({r.get('meeting_date', 'Unknown')})"
                                # Limit each chunk to 300 chars
                                text = r.get('text', '').strip()[:300]
                                cross_meeting_context += f"- [{source}]: {text}\n"
                except Exception as e:
                    logger.warning(f"Failed to fetch linked meeting context: {e}")
            else:
                logger.info("Classifier determined linked context not needed for this question")

        # Format history - limit to 5 messages for token savings
        history_text = ""
        if history:
            history_text = "\nConversation History:\n"
            for msg in history[-5:]:  # Reduced from 10 to 5
                role = msg.get("role", "user")
                content = msg.get("content", "")[:300]  # Limit each message
                history_text += f"{role.upper()}: {content}\n"

        # === CONTEXT TRUNCATION - 5K LIMIT ===
        # Reduced from 20k to 5k chars (~1250 tokens)
        if context and len(context) > 5000:
            logger.info(f"Truncating context from {len(context)} to 5000 chars")
            context = context[-5000:]  # Take most recent content
        
        # Limit cross-meeting context to 1500 chars (3-5 chunks @ 300 chars each)
        if cross_meeting_context and len(cross_meeting_context) > 1500:
            cross_meeting_context = cross_meeting_context[:1500]

        system_prompt = f"""
        You are a helpful AI assistant answering questions about meetings.
        
        Current Meeting Context:
        ---
        {context}
        ---

        {cross_meeting_context}

        {history_text}

        Instructions:
        1. Answer the user's question based on the provided context (Current or Linked Meetings).
        2. If using info from 'Linked Meetings', YOU MUST CITE THE SOURCE exactly as shown in brackets.
        3. If history is provided, use it to understand conversation context.
        4. If the answer is NOT in any context, say you don't have that information in the meeting context.
        5. Be concise and direct.
        """

        try:
            # --- OLLAMA SUPPORT ---
            if model == "ollama":
                ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
                client = AsyncClient(host=ollama_host)
                message = {'role': 'user', 'content': question}
                system_message = {'role': 'system', 'content': system_prompt}
                
                async def stream_ollama():
                    async for part in await client.chat(model=model_name, messages=[system_message, message], stream=True):
                        content = part['message']['content']
                        yield content
                
                return stream_ollama()

            # --- GROQ SUPPORT ---
            elif model == "groq":
                api_key = await db.get_api_key("groq")
                if not api_key:
                    api_key = os.getenv("GROQ_API_KEY")
                if not api_key: 
                    raise ValueError("Groq API key not found.")
                
                from groq import AsyncGroq
                client = AsyncGroq(api_key=api_key)
                
                # Prevent TPM limit errors by restricting output tokens
                completion_tokens = 4096
                if "8b" in model_name: 
                    completion_tokens = 1024
                
                # Initialize stream immediately to catch errors early
                initial_stream = await client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question}
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
                                 
                return stream_groq(initial_stream)

            # --- OPENAI SUPPORT ---
            elif model == "openai":
                api_key = await db.get_api_key("openai")
                if not api_key: raise ValueError("OpenAI API key not found")
                
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=api_key)
                
                # Initialize stream immediately
                initial_stream = await client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question}
                    ],
                    model=model_name,
                    stream=True,
                )
                
                async def stream_openai(stream_iter):
                    async for chunk in stream_iter:
                        content = chunk.choices[0].delta.content or ""
                        if content:
                            yield content
                
                return stream_openai(initial_stream)
            
            # --- CLAUDE SUPPORT ---
            elif model == "claude":
                 api_key = await db.get_api_key("claude")
                 if not api_key: raise ValueError("Anthropic API key not found")
                 
                 from anthropic import AsyncAnthropic
                 client = AsyncAnthropic(api_key=api_key)
                 
                 # Initialize stream immediately
                 initial_stream = await client.messages.create(
                     max_tokens=1024,
                     system=system_prompt,
                     messages=[{"role": "user", "content": question}],
                     model=model_name,
                     stream=True
                 )
                 
                 async def stream_claude(stream_iter):
                     try:
                         async for text in stream_iter.text_stream:
                             yield text
                     except Exception as e:
                         yield f"Error: {str(e)}"
                 
                 return stream_claude(initial_stream)

            # --- GEMINI SUPPORT ---
            elif model == "gemini":
                api_key = await db.get_api_key("gemini")
                if not api_key:
                    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                if not api_key: raise ValueError("Gemini API key not found")
                
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                
                # Create generation config
                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "top_k": 64,
                    "max_output_tokens": 8192,
                }
                
                # Check for Flash model (higher rate limits)
                if "flash" in model_name.lower():
                     # No change needed really, basically same config
                     pass
                     
                gen_model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=generation_config,
                    system_instruction=system_prompt
                )
                
                chat_session = gen_model.start_chat(history=[])
                
                # Send message and get stream
                response = chat_session.send_message(question, stream=True)
                
                async def stream_gemini(response_iterator):
                    try:
                        for chunk in response_iterator:
                            if hasattr(chunk, 'text') and chunk.text:
                                yield chunk.text
                    except Exception as e:
                        logger.error(f"Gemini streaming error: {e}", exc_info=True)
                        yield f"\n\nError during Gemini response: {str(e)}"
                            
                return stream_gemini(response)

            else:
                raise ValueError(f"Unsupported chat model: {model}")

        except Exception as e:
            logger.error(f"Error in chat_about_meeting: {e}", exc_info=True)
            # Re-raise the exception so the caller (API endpoint) can handle it 
            # and return a proper HTTP error code (e.g. 500 or 429)
            raise e

    def cleanup(self):
        """Clean up resources used by the TranscriptProcessor."""
        logger.info("Cleaning up TranscriptProcessor resources")
        try:
            # Close database connections if any
            if hasattr(self, 'db') and self.db is not None:
                # self.db.close()
                logger.info("Database connection cleanup (using context managers)")
                
            # Cancel any active Ollama client sessions
            if hasattr(self, 'active_clients') and self.active_clients:
                logger.info(f"Terminating {len(self.active_clients)} active Ollama client sessions")
                for client in self.active_clients:
                    try:
                        # Close the client's underlying connection
                        if hasattr(client, '_client') and hasattr(client._client, 'close'):
                            asyncio.create_task(client._client.aclose())
                    except Exception as client_error:
                        logger.error(f"Error closing Ollama client: {client_error}", exc_info=True)
                # Clear the list
                self.active_clients.clear()
                logger.info("All Ollama client sessions terminated")
        except Exception as e:
            logger.error(f"Error during TranscriptProcessor cleanup: {str(e)}", exc_info=True)

        