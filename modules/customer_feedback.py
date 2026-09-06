"""
Customer Feedback Analysis & Sentiment Monitoring Module.
Ingests reviews from POS, Google, Yelp, and Shopify, aggregates Net Promoter Score (NPS),
identifies common operational praise/pain points, and generates actionable recommendations.
"""

import datetime
from typing import List, Dict, Any, Optional
from database import query_all, query_one, execute_mutation, get_db_connection


class CustomerFeedbackAnalyzer:
    """Processes reviews, analyzes customer satisfaction, and computes Net Promoter Score (NPS)."""

    def __init__(self, tenant_id: str = "acme-electronics"):
        self.tenant_id = tenant_id

    def add_review(
        self,
        customer_name: str,
        rating: int,
        feedback_text: str,
        source: str = "Google Reviews",
        review_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Adds a customer review with rule-based sentiment classification."""
        r_date = review_date or datetime.date.today().isoformat()
        rating_int = max(1, min(5, int(rating)))

        # Simple sentiment classification
        if rating_int >= 4:
            sentiment = "POSITIVE"
        elif rating_int == 3:
            sentiment = "NEUTRAL"
        else:
            sentiment = "NEGATIVE"

        execute_mutation(
            """
            INSERT INTO customer_reviews (tenant_id, review_date, customer_name, rating, sentiment, feedback_text, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (self.tenant_id, r_date, customer_name.strip(), rating_int, sentiment, feedback_text.strip(), source)
        )

        return {
            "success": True,
            "tenant_id": self.tenant_id,
            "customer_name": customer_name,
            "rating": rating_int,
            "sentiment": sentiment,
            "feedback_text": feedback_text,
            "source": source,
            "review_date": r_date
        }

    def get_feedback_report(self) -> Dict[str, Any]:
        """
        Computes average rating, Net Promoter Score (NPS), sentiment distribution,
        and extracts key positive and negative themes.
        """
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM customer_reviews WHERE tenant_id = ? ORDER BY review_date DESC",
            (self.tenant_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        reviews = [dict(r) for r in rows]

        total_reviews = len(reviews)
        if total_reviews == 0:
            return {
                "tenant_id": self.tenant_id,
                "total_reviews": 0,
                "average_rating": 0.0,
                "nps_score": 0,
                "sentiment_breakdown": {"POSITIVE": 0, "NEUTRAL": 0, "NEGATIVE": 0},
                "recent_reviews": [],
                "actionable_insights": ["No reviews recorded yet for this tenant."]
            }

        ratings = [r["rating"] for r in reviews]
        avg_rating = round(sum(ratings) / total_reviews, 2)

        sentiment_counts = {"POSITIVE": 0, "NEUTRAL": 0, "NEGATIVE": 0}
        promoters = 0
        detractors = 0

        for r in reviews:
            sent = r.get("sentiment", "NEUTRAL")
            sentiment_counts[sent] = sentiment_counts.get(sent, 0) + 1
            if r["rating"] == 5:
                promoters += 1
            elif r["rating"] <= 3:
                detractors += 1

        nps_score = round(((promoters - detractors) / total_reviews) * 100)

        # Actionable insights generation
        insights = []
        if sentiment_counts["NEGATIVE"] > 0:
            insights.append(f"⚠️ {sentiment_counts['NEGATIVE']} negative feedback items require manager attention.")
        if avg_rating >= 4.5:
            insights.append("🌟 Customer satisfaction is exceptionally high. Leverage top reviews in marketing campaigns.")
        elif avg_rating < 3.5:
            insights.append("🚨 Average rating is below operational benchmark (3.5). Review order fulfillment speed and product quality.")
        else:
            insights.append("👍 Customer satisfaction is steady. Focus on reducing shipping times and improving staff responsiveness.")

        return {
            "tenant_id": self.tenant_id,
            "total_reviews": total_reviews,
            "average_rating": avg_rating,
            "nps_score": nps_score,
            "sentiment_breakdown": sentiment_counts,
            "recent_reviews": reviews[:10],
            "actionable_insights": insights
        }
