"""Search Tools: Agentic Web Search (Iterative Refinement)."""
import logging
import json
from typing import Dict, Any, List
from app.tools.base_tool import BaseTool

logger = logging.getLogger(__name__)

class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web. Returns top 20 results. You (the agent) must evaluate if results are relevant. If not, call this tool AGAIN with a refined query."
    
    def _score_result(self, result: Dict[str, str], query_words: set) -> float:
        title = result.get('title', '').lower()
        body = result.get('body', '').lower()
        text = f"{title} {body}"
        score = 0.0
        text_words = set(text.split())
        matches = query_words & text_words
        score += len(matches) * 2.0
        for qw in query_words:
            if len(qw) > 3 and qw in text: score += 1.0
        return score

    def execute(self, params: Dict[str, Any]) -> str:
        query = params.get('query', '')
        # Fetch 20 for broad coverage
        num_results = int(params.get('num_results', 20)) 
        
        if not query:
            return "❌ Error: No search query provided."
        
        logger.info(f"🔍 Agentic Search: Fetching {num_results} results for '{query}'...")
        
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(query, max_results=num_results))
            
            if not raw_results:
                return f"⚠️ SEARCH FAILED: No results found for '{query}'. Try refining your query."
            
            # Sort by relevance (simple scoring)
            query_words = set(query.lower().split())
            scored = []
            for r in raw_results:
                score = self._score_result(r, query_words)
                scored.append((score, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            
            # Format for Agent Evaluation (Top 20)
            # We include Title, Snippet, and URL so the agent can judge relevance
            output_lines = [f"🔍 SEARCH RESULTS FOR: '{query}'", f"Total Found: {len(raw_results)}", "-"*40]
            
            for i, (score, r) in enumerate(scored, 1):
                title = r.get('title', 'No Title')
                body = r.get('body', 'No Description')
                url = r.get('href', 'No URL')
                # Truncate body for brevity in context
                body_short = body[:150] + "..." if len(body) > 150 else body
                output_lines.append(f"{i}. [{score:.1f}] {title}\n   Snippet: {body_short}\n   URL: {url}")
            
            # Add Instruction for the Agent
            output_lines.append("-"*40)
            output_lines.append("🤖 AGENT INSTRUCTION: Review these 20 results.")
            output_lines.append("- If they answer the user's question: Summarize the top 3-5 points and cite URLs.")
            output_lines.append("- If they are IRRELEVANT or MISSING info: Call 'web_search' AGAIN with a MORE SPECIFIC query.")
            
            return "\n".join(output_lines)
            
        except ImportError:
            return "❌ Error: 'ddgs' library not installed."
        except Exception as e:
            logger.error(f"Search failed: {e}", exc_info=True)
            return f"❌ Search failed: {str(e)}"
