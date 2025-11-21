import json
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger("darkstar.voice")


def get_advice(analyst_report: Dict[str, Any], config: Dict[str, Any], secrets: Dict[str, Any]) -> str:
    """
    Send Analyst report to LLM and get a text summary.
    """
    advisor_cfg = config.get("advisor", {})
    if not advisor_cfg.get("enable_llm", False):
        return "Advisor is disabled in config."

    api_key = secrets.get("openrouter_api_key")
    if not api_key or "sk-" not in api_key:
        return "OpenRouter API Key missing or invalid in secrets.yaml."

    model = advisor_cfg.get("model", "google/gemini-flash-1.5")
    personality = advisor_cfg.get("personality", "concise")

    system_prompt = (
        "You are Darkstar, an intelligent home energy assistant. "
        "Analyze the provided JSON report of optimal run-times for appliances. "
        "Give a specific, actionable recommendation for the user. "
        "Compare Grid (Night) vs Solar (Day) options if both exist. "
    )

    if personality == "concise":
        system_prompt += "Be extremely brief. Max 2 sentences. Focus on savings."
    elif personality == "technical":
        system_prompt += "Include price delta and kWh details. Be precise."
    else:
        system_prompt += "Be friendly and helpful. Use an emoji. Max two sentences."

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/darkstar",
            },
            data=json.dumps(
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(analyst_report)},
                    ],
                }
            ),
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()
        else:
            logger.error(f"OpenRouter Error {response.status_code}: {response.text}")
            return "Sorry, I couldn't reach the AI cloud."
    except Exception as e:
        logger.error(f"Voice Generation Failed: {e}")
        return "Error generating advice."
