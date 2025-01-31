import json
from datetime import datetime
from typing import List, Dict, Any

import httpx
import numpy as np
from fastapi import HTTPException
from openai import OpenAI

from config import WEATHER_CONFIG, FLOOD_RISK_CONFIG
from models import Point

client = OpenAI(api_key="sk-svcacct-8Y_mxVNnuZW8S6GIGVsoHpqNcqONmgUyxxVxY00u5y4ZD42MVRr8SYUFW0L0dePw_n-nVT3BlbkFJ9kQPd-v1NbAr3MQl58elUVR-_woB3tMX_6DjGbfk09NQJULKKZBytuXnWiO6eSbbVk-AA")


async def get_weather_forecast(point: Point) -> Dict[str, Any]:
    """Get weather forecast from API"""
    try:
        url = f"https://api.weatherapi.com/v1/forecast.json"
        params = {
            "key": WEATHER_CONFIG["api_key"],
            "q": f"{point.lat},{point.lng}",
            "days": WEATHER_CONFIG["forecast_days"]
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(status_code=response.status_code, detail="Weather API error")
    except Exception as e:
        return {
            "current": {
                "temp_c": 20,
                "precip_mm": 0,
                "humidity": 50,
                "condition": {"text": "Unknown"}
            },
            "forecast": {
                "forecastday": [{
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "day": {
                        "totalprecip_mm": 0,
                        "avgtemp_c": 20
                    }
                } for _ in range(7)]
            }
        }


async def get_elevation_data(point: Point) -> float:
    """Get elevation data from Maptiler API"""
    try:
        zoom = 12
        lat, lng = point.lat, point.lng
        n = 2 ** zoom
        xtile = int((lng + 180) / 360 * n)
        ytile = int((1 - np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat))) / np.pi) / 2 * n)

        url = f"https://api.maptiler.com/tiles/terrain-rgb/{zoom}/{xtile}/{ytile}.png"
        params = {"key": "mcUdBlpX6o8IFQ03OMfE"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                return 100  # Default elevation for example
            else:
                raise HTTPException(status_code=response.status_code, detail="Elevation API error")
    except Exception as e:
        return 100  # Default elevation


async def analyze_with_openai(data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze data using OpenAI API"""
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a flood risk analysis expert. Analyze the provided data including:\n"
                    "- Weather conditions and forecasts\n"
                    "- Terrain elevation and nearby waterways\n"
                    "- Existing buildings and infrastructure\n"
                    "- Known flood-prone areas and inundation zones\n"
                    "- Land use patterns\n"
                    "Provide a comprehensive flood risk assessment considering all these factors.\n"
                    "Always respond with a valid JSON object containing:\n"
                    "- riskLevel (LOW/MEDIUM/HIGH)\n"
                    "- riskScore (0-1)\n"
                    "- mainFactors (array of key risk factors)\n"
                    "- concerns (array of specific concerns)\n"
                    "- recommendations (array of actionable recommendations)\n"
                    "- explanation (detailed analysis string)\n"
                )
            },
            {
                "role": "user",
                "content": json.dumps(data)
            }
        ]

        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages
        )

        response_data = json.loads(response.choices[0].message.content)
        response_data["weather"] = data["weather"]["current"]
        return response_data

    except Exception as e:
        print (f"Aaaaaaaaaaaaaaa {e}")
        return generate_local_analysis(data)


def generate_local_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate local analysis when API is unavailable"""
    risk_score = 0
    factors = []
    concerns = []
    recommendations = []

    # Analyze waterways
    if data['waterways']:
        closest_waterway = min(w['distance'] for w in data['waterways'])
        if closest_waterway < 500:
            risk_score += 0.3
            factors.append('Close proximity to waterway')
            concerns.append(f"Waterway within {round(closest_waterway)}m")

    # Analyze flooding data
    if data['flooding_data']:
        if data['flooding_data']['known_inundation_areas'] > 0:
            risk_score += 0.4
            factors.append('Located in known inundation area')
            concerns.append('Historical flooding recorded in this area')

    # Analyze elevation
    if data['terrain']['elevation'] < FLOOD_RISK_CONFIG['elevation_threshold']:
        risk_score += 0.3
        factors.append('Low elevation relative to waterways')
        concerns.append('Area at risk during heavy rainfall')

    # Determine risk level
    risk_level = 'LOW'
    if risk_score > 0.7:
        risk_level = 'HIGH'
        recommendations.append('Consider flood protection measures')
    elif risk_score > 0.3:
        risk_level = 'MEDIUM'
        recommendations.append('Monitor water levels during rainy seasons')

    return {
        "riskLevel": risk_level,
        "riskScore": min(1, risk_score),
        "mainFactors": factors,
        "concerns": concerns,
        "recommendations": recommendations,
        "explanation": f"Analysis based on {len(factors)} main risk factors including proximity to waterways, historical flooding data, and terrain characteristics."
    }


def calculate_relative_elevation(elevation: float, waterways: List[Dict[str, Any]]):
    """Calculate elevation relative to nearby waterways"""
    if not waterways:
        return None
    waterway_elevations = [w['properties'].get('ele', elevation) for w in waterways]
    return elevation - min(waterway_elevations)
