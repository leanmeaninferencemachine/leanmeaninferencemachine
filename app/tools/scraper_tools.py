# app/tools/scraper_tools.py
"""
Scraper Agent for LMIM OS v2.1
- Single and batch URL scraping
- Robots.txt compliance
- AI-powered analysis with purpose setting
"""

import re
import logging
import asyncio
import aiohttp
import requests
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Any
from bs4 import BeautifulSoup
import urllib.robotparser
from datetime import datetime

logger = logging.getLogger(__name__)


class ScraperAgent:
    """Handles web scraping with robots.txt compliance and rate limiting."""

    def __init__(self):
        self.user_agent = "LMIM-OS/2.1 (+https://lmim.tech)"
        self.timeout = 30
        self.max_concurrent = 3
        self.max_urls = 10
        self.max_text_length = 8000
        self.max_links = 50

    def _check_robots(self, url: str) -> bool:
        """Check if scraping is allowed by robots.txt."""
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            return rp.can_fetch(self.user_agent, url)
        except Exception as e:
            logger.debug(f"Robots.txt check failed for {url}: {e}")
            return True  # Proceed cautiously if can't read

    async def scrape_single(self, session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
        """Scrape a single URL asynchronously."""
        if not self._check_robots(url):
            return {
                "url": url,
                "success": False,
                "error": "Blocked by robots.txt",
                "timestamp": datetime.now().isoformat()
            }

        try:
            async with session.get(
                url,
                headers={"User-Agent": self.user_agent},
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                if response.status != 200:
                    return {
                        "url": url,
                        "success": False,
                        "error": f"HTTP {response.status}",
                        "timestamp": datetime.now().isoformat()
                    }

                html = await response.text()
                soup = BeautifulSoup(html, "lxml")

                # Remove noise elements
                for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                    tag.decompose()

                # Extract metadata
                title_tag = soup.find("title")
                title = title_tag.get_text().strip() if title_tag else ""

                meta_desc = soup.find("meta", attrs={"name": "description"})
                description = meta_desc.get("content", "").strip() if meta_desc else ""

                meta_keywords = soup.find("meta", attrs={"name": "keywords"})
                keywords = meta_keywords.get("content", "").strip() if meta_keywords else ""

                # Extract main text
                text = soup.get_text(separator="\n", strip=True)
                lines = [l for l in text.splitlines() if l.strip()]
                clean_text = "\n".join(lines)[:self.max_text_length]

                # Extract links (internal + external)
                links = []
                internal_links = []
                external_links = []
                base_domain = urlparse(url).netloc

                for a in soup.find_all("a", href=True):
                    href = urljoin(url, a["href"])
                    if href.startswith(("http://", "https://")):
                        links.append(href)
                        if base_domain in href:
                            internal_links.append(href)
                        else:
                            external_links.append(href)

                # Remove duplicates
                links = list(set(links))[:self.max_links]
                internal_links = list(set(internal_links))[:self.max_links]
                external_links = list(set(external_links))[:self.max_links]

                return {
                    "url": url,
                    "success": True,
                    "title": title,
                    "description": description,
                    "keywords": keywords,
                    "text": clean_text,
                    "word_count": len(clean_text.split()),
                    "size_kb": round(len(html) / 1024, 2),
                    "status_code": response.status,
                    "links": links,
                    "internal_links": internal_links,
                    "external_links": external_links,
                    "timestamp": datetime.now().isoformat()
                }

        except asyncio.TimeoutError:
            return {
                "url": url,
                "success": False,
                "error": f"Timeout after {self.timeout}s",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Scrape failed for {url}: {e}")
            return {
                "url": url,
                "success": False,
                "error": str(e)[:200],
                "timestamp": datetime.now().isoformat()
            }

    async def scrape_batch(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Scrape multiple URLs concurrently with rate limiting."""
        if not urls:
            return []

        # Limit number of URLs
        urls = urls[:self.max_urls]

        # Rate limiting semaphore
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def scrape_with_limit(session, url):
            async with semaphore:
                return await self.scrape_single(session, url)

        async with aiohttp.ClientSession() as session:
            tasks = [scrape_with_limit(session, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and return only dict results
        return [r for r in results if isinstance(r, dict)]

    def scrape_sync(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Synchronous wrapper for scrape_batch."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(self.scrape_batch(urls))
        finally:
            loop.close()
        return results


class ScraperAnalyzer:
    """AI-powered analysis of scraped content."""

    @staticmethod
    def format_for_analysis(results: List[Dict[str, Any]], purpose: str) -> str:
        """Format scraped results for AI analysis."""
        if not results:
            return "No content to analyze."

        context = f"Purpose: {purpose}\n\n"
        context += "Scraped Content:\n"
        context += "=" * 50 + "\n"

        for i, r in enumerate(results, 1):
            if r.get("success"):
                context += f"\n[{i}] URL: {r['url']}\n"
                context += f"Title: {r.get('title', 'N/A')}\n"
                context += f"Description: {r.get('description', 'N/A')[:500]}\n"
                context += f"Content: {r.get('text', '')[:3000]}\n"
                context += "-" * 30 + "\n"
            else:
                context += f"[{i}] URL: {r['url']} - FAILED: {r.get('error', 'Unknown error')}\n"

        return context

    @staticmethod
    async def analyze(results: List[Dict[str, Any]], purpose: str) -> Optional[str]:
        """Use LMIM to analyze scraped content."""
        if not purpose or not results:
            return None

        try:
            from app.model_interface import query_model

            formatted = ScraperAnalyzer.format_for_analysis(results, purpose)

            prompt = f"""IMPORTANT: You MUST provide a detailed analysis. Do NOT just say "Understood".

A user has scraped websites with this purpose: {purpose}

Here is the scraped content:
{formatted}

TASK: Based ONLY on the scraped content above, provide a thorough analysis that:
1. Summarizes what was found on each website
2. Answers the user's specific purpose
3. Lists any key information (dates, prices, contacts, etc.)

If the purpose asks for comparison, compare the websites.
If the purpose asks for summary, summarize the key points.
Be specific and reference the actual content shown above.

Analysis:"""

            analysis = query_model(
                prompt=prompt,
                user_id="scraper_agent",
                builder_mode=False,
                max_tool_iterations=0,
                system_override="You are a helpful web content analyzer. Analyze the provided content and answer the user's purpose directly. Be specific and thorough."
            )

            return analysis

        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return f"Analysis failed: {str(e)}"

    def analyze_sync(self, results: List[Dict[str, Any]], purpose: str) -> Optional[str]:
        """Synchronous wrapper for analyze."""
        if not purpose or not results:
            return None

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.analyze(results, purpose))
        finally:
            loop.close()


# Helper function for direct tool calling (for agent use)
def scrape_website(url: str, extract_text_only: bool = True) -> Dict[str, Any]:
    """
    Tool function for LMIM agent to scrape a website.
    Compatible with the tool calling system.
    """
    scraper = ScraperAgent()
    result = scraper.scrape_sync([url])[0] if scraper.scrape_sync([url]) else None

    if not result or not result.get("success"):
        return {"ok": False, "error": result.get("error", "Scrape failed") if result else "No result"}

    if extract_text_only:
        return {
            "ok": True,
            "url": result["url"],
            "title": result["title"],
            "text": result["text"],
            "word_count": result["word_count"]
        }

    return {"ok": True, "result": result}
