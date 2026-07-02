import asyncio
import sys
import logging
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import os

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import AsyncSessionLocal
from app.models.news import NewsArticle
from app.services.mc_nlp import analyze_mc_article_dict
from app.services.nlp_service import analyze_article_dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_backfill():
    async with AsyncSessionLocal() as session:
        logger.info("Fetching MC articles...")
        query = select(NewsArticle).where(NewsArticle.source.like("moneycontrol%"))
        result = await session.execute(query)
        articles = result.scalars().all()
        
        logger.info(f"Found {len(articles)} MC articles. Processing in batches...")
        
        updated = 0
        batch = []
        for article in articles:
            try:
                headline = article.title or ""
                summary = article.text or ""
                
                # Analyze using the new specific logic
                res = analyze_mc_article_dict(headline, summary, article.source)
                
                # We could compare to see if it changed, but let's just update
                article.sentiment = res["sentiment"]
                article.sentiment_score = res["sentiment_score"]
                article.confidence = res["confidence"]
                article.language = res["language"]
                article.threat_level = res["threat_level"]
                article.threat_category = res["threat_category"]
                
                # Ensure entities are stored properly (often handled at ORM level for JSON)
                article.entities = res["entities"]
                article.source_credibility = res["source_credibility"]
                
                updated += 1
                
                if updated % 500 == 0:
                    logger.info(f"Processed {updated}...")
                    await session.commit()
            except Exception as e:
                logger.error(f"Error processing {article.url}: {e}")
        
        await session.commit()
        logger.info(f"Backfill complete! Updated {updated} articles.")

if __name__ == "__main__":
    asyncio.run(run_backfill())
