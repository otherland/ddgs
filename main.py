from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
import aiohttp
from newspaper import Article
from duckduckgo_search import AsyncDDGS
from duckduckgo_search.exceptions import RatelimitException, DuckDuckGoSearchException
import random
from urllib.parse import urlparse
from typing import List, Dict
import logging

# Initialize FastAPI app
app = FastAPI()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Request model
class SearchRequest(BaseModel):
    keyword: str

def clean_text(text: str) -> str:
    if not text:
        return ""
    return ''.join(char if ord(char) < 128 else ' ' for char in text).strip()

async def fetch_and_parse_article(session: aiohttp.ClientSession, url: str) -> Dict:
    try:
        article = Article(url)
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                return {"url": url, "error": f"HTTP {response.status}"}
            html = await response.text()
            
        article.set_html(html)
        article.parse()
        
        return {
            "title": clean_text(article.title),
            "text": clean_text(article.text[:10000]),
        }
    except Exception as e:
        return {"url": url, "error": str(e)}

async def get_material(keyword: str, max_retries=5, initial_delay=1):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    async with AsyncDDGS(headers=headers) as ddgs:
        for attempt in range(max_retries):
            try:
                results = await ddgs.atext(keyword, max_results=15)
                
                if not results:
                    return ""

                urls = []
                seen_domains = set()
                for result in results:
                    url = result.get('href')
                    if not url:
                        continue
                    
                    domain = urlparse(url).netloc
                    if domain in seen_domains:
                        continue
                    seen_domains.add(domain)
                    urls.append(url)

                async with aiohttp.ClientSession(headers=headers) as session:
                    tasks = []
                    for url in urls:
                        task = fetch_and_parse_article(session, url)
                        tasks.append(task)
                    
                    articles = await asyncio.gather(*tasks, return_exceptions=True)
                    formatted_results = []
                    for article in articles:
                        if isinstance(article, dict) and "error" not in article:
                            formatted_results.append(f"Title: {article['title']}")
                            formatted_results.append(f"Text: {article['text']}")
                            formatted_results.append("-" * 5)

                    return "\n".join(formatted_results)

            except (RatelimitException, DuckDuckGoSearchException) as e:
                if attempt == max_retries - 1:
                    raise
                
                delay = initial_delay * (2 ** attempt) + random.uniform(0, 1)
                await asyncio.sleep(delay)
            
            except Exception as e:
                raise

@app.get("/")
async def root():
    return {"message": "Welcome to the Search API! Send a POST request to /search with a keyword to search."}

@app.post("/search")
async def search(request: SearchRequest):
    try:
        results = await get_material(request.keyword)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))