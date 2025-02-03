import json
from pathlib import Path

import geopandas as gpd

import qrcode
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client

from config import TWILIO_PHONE_NUMBER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
from models import AnalysisRequest
from storage import SpatialDataStore
from utils import get_weather_forecast, get_elevation_data, calculate_relative_elevation, analyze_with_openai

app = FastAPI(title="Flood Risk Analysis Application")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create necessary directories
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)


PHONE_NUMBERS = ["+40749884014", "+40767911992", "+40745480204"]

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def read_root():
    """Serve the main HTML page"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/shapefile/{filename}")
async def get_shapefile(filename: str):
    from pathlib import Path

    file_path = Path("data") / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found")

    # Set proper headers for binary file transfer
    headers = {
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Access-Control-Expose-Headers': 'Content-Disposition'
    }

    return FileResponse(
        path=file_path,
        headers=headers,
        media_type='application/octet-stream'
    )


@app.get("/generate-group-qr")
async def generate_group_qr():
    """Generate QR code for WhatsApp group join link"""
    # Replace this with your actual WhatsApp group invite link
    whatsapp_group_link = "https://chat.whatsapp.com/FpJYNGfOn7SBki7bJgn9y8"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(whatsapp_group_link)
    qr.make(fit=True)

    qr_image = qr.make_image(fill_color="black", back_color="white")
    qr_path = "static/qr/group_qr.png"
    qr_image.save(qr_path)

    return FileResponse(qr_path)


@app.post("/api/send-flood-alert")
async def send_group_message():

    """Send message to WhatsApp group"""
    try:
        message = """
            🚨 FLOOD RISK ALERT - HIGH PRIORITY 🚨

📍 Area Risk Assessment:
• Risk Level: HIGH (8.5/10)
• Affected: 156 buildings, 23 transport routes
• Known Flood Zones: 3 active areas

🌊 Critical Concerns:
• Power substation at risk (50,000 households)
• Both evacuation routes show flooding >30cm
• 3 schools & 1 care home in danger zone
• Business district (£10M+ annual revenue) threatened
• 2 fuel storage facilities at contamination risk

⚠️ Current Conditions:
• Temp: 22°C
• Rain: 45mm
• Wind: 15 km/h
• Status: Heavy Rain

🔍 Key Risk Factors:
• 100m from Thames flood plain
• Area 2.5m below surroundings
• Drainage system over 30 years old
• 65% clay soil reducing drainage
• 40% reduction in natural drainage
• 3 major floods in past 5 years

👥 Vulnerable Population:
• 25% elderly/mobility-impaired residents
• Emergency assistance required

🚨 IMMEDIATE ACTIONS REQUIRED:
1. Monitor flood warning systems
2. Prepare for possible evacuation
3. Clear drainage systems
4. Check flood barriers

📱 Stay alert for updates. Follow official channels for evacuation notices.

🔗 Emergency Contacts:
• Flood Helpline: [Insert Number]
• Emergency Services: [Insert Number]
• Council Support: [Insert Number]

Please share with neighbors and vulnerable residents. Stay safe!

#FloodAlert #EmergencyResponse #CommunitySupport
        """
        messages = []
        for number in PHONE_NUMBERS:
            message = twilio_client.messages.create(
                from_=TWILIO_PHONE_NUMBER,
                body=message,
                to=f"whatsapp:{number}"
            )
            messages.append(message.sid)

        return {
            "status": "success",
            "message_sids": messages
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze")
async def analyze_location(request: AnalysisRequest):
    """Analyze flood risk for a location"""
    try:
        data_store = SpatialDataStore()
        # Gather all required data
        weather = await get_weather_forecast(request.point)
        elevation_data = await get_elevation_data(request.point)
        nearby_waterways = data_store.find_nearby_waterways(request.point, request.radius)
        # flooding_data = data_store.get_flooding_data(request.point, request.radius)

        # Prepare analysis data
        analysis_data = {
            "location": {
                "latitude": request.point.lat,
                "longitude": request.point.lng,
                "elevation": {
                    "value": elevation_data,
                    "unit": "meters"
                }
            },
            "weather": {
                "current": {
                    "temperature": weather["current"]["temp_c"],
                    "precipitation": weather["current"]["precip_mm"],
                    "humidity": weather["current"]["humidity"],
                    "condition": weather["current"]["condition"]["text"],
                    "wind_speed": weather["current"]["wind_kph"],
                    "pressure": weather["current"]["pressure_mb"]
                },
                "forecast": [
                    {
                        "date": day["date"],
                        "precipitation_mm": day["day"]["totalprecip_mm"],
                        "avg_temp_c": day["day"]["avgtemp_c"],
                        "max_wind_kph": day["day"]["maxwind_kph"],
                        "chance_of_rain": day["day"]["daily_chance_of_rain"]
                    }
                    for day in weather["forecast"]["forecastday"]
                ]
            },
            "waterways": nearby_waterways,
            "flooding_data": None,
            "analysis_radius": request.radius,
            "terrain": {
                "elevation": elevation_data,
                "elevation_relative_to_waterways": calculate_relative_elevation(elevation_data, nearby_waterways),
                "waterway_count": len(nearby_waterways),
                "waterway_types": list(set(w["type"] for w in nearby_waterways))
            }
        }

        # Get AI analysis
        risk_analysis = await analyze_with_openai(analysis_data)
        return risk_analysis

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    # data_store = SpatialDataStore()
    # # data_store.get_waterway()
    # gdf = gpd.read_file("/Users/andreihilote/Downloads/Archive 8/flooding_area/P03_MOD_InundationExtent.shp")
    # #
    # # # Convert to GeoJSON and store in database
    # geojson_data = json.loads(gdf.to_json())
    # #
    # #
    # data_store.store_flooding_data(geojson_data)
    # #
    # data_store.store_waterway_data(geojson_data)

    uvicorn.run(app, host="0.0.0.0", port=8000)